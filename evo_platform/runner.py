"""Durable worker. Ambiguous submissions require reconciliation, never resubmission."""
import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path
from .connectors import make_connector, QuestionMismatch, ConnectorError
from .evaluation import evaluate_output
from .store import Store, encode, normalize


@contextmanager
def worker_lock(store, run_id):
    """Kernel lock survives UI reruns and releases automatically after process death."""
    import os
    import uuid
    uuid.UUID(run_id)
    folder = Path(store.path).parent / '.workers'
    folder.mkdir(exist_ok=True)
    with (folder / (run_id + '.lock')).open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run_batch(store, run_id, connector_factory=make_connector, evaluator=evaluate_output):
    run = store.rows('SELECT application_id FROM runs WHERE id=?', (run_id,))[0]
    # A second run cannot silently multiply load against the same application.
    with worker_lock(store, run['application_id']) as application_available:
        if application_available:
            with worker_lock(store, run_id) as acquired:
                if acquired:
                    _run_batch(store, run_id, connector_factory, evaluator)
    status = store.rows('SELECT status FROM runs WHERE id=?', (run_id,))[0]['status']
    if status in ('completed', 'completed_with_errors'):
        from .cloud import sync_run
        sync_run(store, run_id)


def _run_batch(store, run_id, connector_factory, evaluator):
    run = store.rows('SELECT * FROM runs WHERE id=?', (run_id,))[0]
    if run['status'] in ('cancelled', 'completed', 'completed_with_errors'):
        return
    # A database compare-and-swap permits only one worker per run.
    if not store.execute("UPDATE runs SET status='running' WHERE id=? AND status IN ('pending','paused','interrupted')", (run_id,)):
        return
    config = json.loads(run['config'])
    app = config['application']
    connector = connector_factory(app['kind'], json.loads(app['config']))
    try:
        for attempt in range(min(3, max(1, int(config.get('connect_attempts', 2))))):
            try:
                connector.connect()
                break
            except Exception:
                connector.close()
                if attempt + 1 >= min(3, max(1, int(config.get('connect_attempts', 2)))):
                    raise
                time.sleep(min(2 ** attempt, 4))
        processed = 0
        for row in store.results(run_id):
            status = store.rows('SELECT status FROM runs WHERE id=?', (run_id,))[0]['status']
            if status != 'running':
                break
            row = store.rows('SELECT * FROM results WHERE id=?', (row['id'],))[0]
            if row['state'] not in ('pending', 'captured'):
                continue
            snapshot = json.loads(row['snapshot'])
            started = time.monotonic()
            try:
                if row['state'] == 'captured':
                    actual = json.loads(row['actual'])
                else:
                    try:
                        connector.start_session(snapshot)
                    except QuestionMismatch as mismatch:
                        matches = []
                        for candidate in store.results(run_id):
                            if candidate['state'] != 'pending':
                                continue
                            candidate_snapshot = json.loads(candidate['snapshot'])
                            if candidate_snapshot['technology_id'] != snapshot['technology_id']:
                                continue
                            if mismatch.external_id is not None:
                                matched = str(candidate_snapshot['external_id']) == mismatch.external_id
                            else:
                                matched = normalize(candidate_snapshot['question']) == normalize(mismatch.question)
                            if matched:
                                matches.append((candidate, candidate_snapshot))
                        if not matches or len({item[1]['question_id'] for item in matches}) != 1:
                            raise ConnectorError('No unambiguous pending case matches the displayed question; no answer submitted')
                        row, snapshot = matches[0]
                    # Commit BEFORE calling submit: a crash cannot cause a duplicate answer.
                    if not store.execute("UPDATE results SET state='submitting',updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='pending'", (row['id'],)):
                        continue
                    actual = connector.submit(snapshot, row['id'])
                    if actual.get('question_id') is not None and str(actual['question_id']) != str(snapshot['external_id']):
                        raise ValueError('Response question ID does not match submitted question')
                    if not any(actual.get(k) is not None for k in ('output', 'feedback', 'score')):
                        raise ValueError('Application response contains no evaluable output')
                    store.execute("UPDATE results SET state='captured',actual=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (encode(actual), row['id']))
                metrics = evaluator(snapshot, actual, config)
                statuses = [m['status'] for m in metrics.values()]
                final = 'evaluation_error' if 'error' in statuses else ('failed' if 'failed' in statuses else ('partial' if 'unavailable' in statuses and 'passed' in statuses else ('passed' if 'passed' in statuses else 'not_evaluated')))
                store.execute('UPDATE results SET state=?,metrics=?,duration=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?', (final, encode(metrics), time.monotonic() - started, row['id']))
            except Exception as exc:
                current = store.rows('SELECT state FROM results WHERE id=?', (row['id'],))[0]['state']
                state = 'needs_review' if current == 'submitting' else ('evaluation_error' if current == 'captured' else 'execution_error')
                # Exception messages from providers may contain tokens/URLs; persist type only.
                message = str(exc) if isinstance(exc, ConnectorError) else type(exc).__name__ + ': inspect connection/reference configuration; no automatic resubmission'
                store.execute('UPDATE results SET state=?,error=?,duration=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (state, message, time.monotonic() - started, row['id']))
            processed += 1
            if processed >= int(config.get('batch_size', 100)):
                store.execute("UPDATE runs SET status='paused' WHERE id=? AND status='running'", (run_id,))
                break
            time.sleep(max(0, min(float(config.get('interval', 1)), 60)))
        update_consistency(store, run_id, config)
        remaining = store.rows("SELECT COUNT(*) n FROM results WHERE run_id=? AND state IN ('pending','captured')", (run_id,))[0]['n']
        if not remaining:
            errors = store.rows("SELECT COUNT(*) n FROM results WHERE run_id=? AND state IN ('needs_review','submitting','execution_error','evaluation_error')", (run_id,))[0]['n']
            store.execute("UPDATE runs SET status=? WHERE id=? AND status IN ('running','paused')", ('completed_with_errors' if errors else 'completed', run_id))
        else:
            store.execute("UPDATE runs SET status='paused' WHERE id=? AND status='running'", (run_id,))
    except Exception as exc:
        store.execute("UPDATE results SET error=? WHERE run_id=? AND state='pending'", (type(exc).__name__ + ': connection could not be established', run_id))
        store.execute("UPDATE runs SET status='interrupted' WHERE id=? AND status='running'", (run_id,))
    finally:
        connector.close()
        actor = config.get('initiated_by')
        if actor:
            from .identity import log_activity
            state = store.rows('SELECT status FROM runs WHERE id=?', (run_id,))[0]['status']
            log_activity(store, actor, 'RUN_' + state.upper(), run_id)


def update_consistency(store, run_id, config):
    if 'Evaluation consistency' not in config.get('metrics', []):
        return
    import math
    groups = {}
    for row in store.results(run_id):
        snapshot = json.loads(row['snapshot'])
        case = json.loads(snapshot['content'])
        reference = snapshot.get('reference')
        if case.get('equivalence_group') and snapshot['validation'] == 'approved' and reference and reference['validation'] == 'approved':
            key = (case['equivalence_group'], reference['id'], snapshot['question_id'])
            groups.setdefault(key, []).append(row)
    for rows in groups.values():
        scores = [json.loads(row['actual'] or '{}').get('score') for row in rows]
        if len(rows) < 2 or not all(isinstance(score, (int, float)) and math.isfinite(score) for score in scores):
            metric = {'status': 'unavailable', 'reason': 'At least two completed equivalent cases with numeric scores are required'}
        else:
            tolerance = float(config.get('consistency_tolerance', 1))
            spread = max(scores) - min(scores)
            passed = spread <= tolerance
            metric = {'status': 'passed' if passed else 'failed', 'score': float(passed), 'quality_score': float(passed), 'threshold': 1, 'reason': f'Equivalent-answer candidate score spread {spread}; configured tolerance {tolerance}'}
        for row in rows:
            if row['state'] not in ('passed', 'failed', 'partial', 'not_evaluated'):
                continue
            metrics = json.loads(row['metrics'] or '{}')
            metrics['Evaluation consistency'] = metric
            states = [m['status'] for m in metrics.values()]
            state = 'failed' if 'failed' in states else ('partial' if 'unavailable' in states and 'passed' in states else ('passed' if 'passed' in states else 'not_evaluated'))
            store.execute('UPDATE results SET metrics=?,state=? WHERE id=?', (encode(metrics), state, row['id']))


def recover(store, run_id):
    """Call only after confirming the prior worker has exited."""
    with worker_lock(store, run_id) as acquired:
        if not acquired:
            raise ValueError('The prior worker is still running')
        store.execute("UPDATE results SET state='needs_review',error='Interrupted during submission; reconcile with application before any new test' WHERE run_id=? AND state='submitting'", (run_id,))
        store.execute("UPDATE runs SET status='interrupted' WHERE id=? AND status NOT IN ('cancelled','completed')", (run_id,))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run_batch(Store(args.db), args.run)
