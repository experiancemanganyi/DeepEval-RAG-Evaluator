"""Publish saved test snapshots and measured results; never re-call the target or judge."""
import argparse
import json
import os
import uuid
from .store import Store


def build_cloud_payload(store, run_id):
    from deepeval.dataset import Golden
    from deepeval.test_case import LLMTestCase
    goldens, tests, measurements = [], [], {}
    for row in store.results(run_id):
        snap = json.loads(row['snapshot'])
        case = json.loads(snap['content'])
        actual = json.loads(row['actual'] or '{}')
        ref = snap.get('reference')
        approved_ref = json.loads(ref['content']) if ref and ref['validation'] == 'approved' else None
        metadata = {'local_run_id': run_id, 'local_result_id': row['id'],
                    'question_id': snap['external_id'], 'technology': snap['technology'],
                    'validation': snap['validation'], 'execution_state': row['state'],
                    'approved_reference': approved_ref, 'captured_response': actual,
                    'local_metrics': json.loads(row['metrics'] or '{}'), 'execution_error': row['error']}
        input_text = json.dumps({'question': snap['question'], 'candidate_answer': case['candidate_input']})
        output = actual.get('output') or json.dumps(actual)
        expected = case.get('expected_output') if snap['validation'] == 'approved' else None
        golden = Golden(input=input_text, actual_output=output if actual else None,
                        expected_output=expected, additional_metadata=metadata, name=row['id'])
        goldens.append(golden)
        tests.append(LLMTestCase(input=input_text, actual_output=output, expected_output=expected,
                                additional_metadata=metadata, name=row['id']))
        measurements[row['id']] = metadata['local_metrics']
        if not measurements[row['id']]:
            measurements[row['id']] = {'Execution status': {'status': 'unavailable',
                'reason': row['error'] or 'No metric completed for this case'}}
    return goldens, tests, measurements


def recorded_metric(name, measurements):
    from deepeval.metrics import BaseMetric

    class RecordedMetric(BaseMetric):
        def __init__(self):
            self.threshold = .5
            self.async_mode = False
            self.strict_mode = False

        @property
        def __name__(self):
            return name

        def measure(self, test_case, *args, **kwargs):
            metric = measurements[test_case.name].get(name, {'status': 'unavailable', 'reason': 'Not selected for this case'})
            self.error = None
            self.score = metric.get('score')
            self.threshold = metric.get('threshold', .5)
            self.reason = metric.get('reason', '')
            self.success = metric['status'] == 'passed'
            if metric['status'] not in ('passed', 'failed'):
                self.error = metric['status'] + ': ' + self.reason
                raise ValueError(self.error)
            return self.score

        async def a_measure(self, test_case, *args, **kwargs):
            return self.measure(test_case)

        def is_successful(self):
            return self.success

    return RecordedMetric()


def sync_run(store, run_id, publisher=None):
    from .runner import worker_lock
    lock_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'cloud:' + run_id))
    with worker_lock(store, lock_id) as acquired:
        if not acquired:
            return
        store.execute('INSERT OR IGNORE INTO cloud_sync(run_id,dataset_alias) VALUES(?,?)', (run_id, 'evo-' + run_id))
        status = store.rows('SELECT * FROM cloud_sync WHERE run_id=?', (run_id,))[0]
        if status['state'] == 'completed':
            return
        if not os.getenv('CONFIDENT_API_KEY'):
            store.execute("UPDATE cloud_sync SET state='waiting_for_key',message='Add your Confident AI key in Settings, then Sync to Confident AI.' WHERE run_id=?", (run_id,))
            return
        store.execute("UPDATE cloud_sync SET state='uploading',message='Uploading saved test data and results',updated_at=CURRENT_TIMESTAMP WHERE run_id=?", (run_id,))
        try:
            link = (publisher or publish)(store, run_id, status)
            if not link:
                raise ValueError('Cloud did not return a test-run link')
            store.execute("UPDATE cloud_sync SET state='completed',confident_link=?,message='Dataset and measured results uploaded',updated_at=CURRENT_TIMESTAMP WHERE run_id=?", (link, run_id))
        except Exception as exc:
            store.execute("UPDATE cloud_sync SET state='failed',message=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                          (type(exc).__name__ + ': cloud upload was not confirmed. Retry sync; it never resubmits interview answers. A timeout may have created a cloud report.', run_id))


def publish(store, run_id, status):
    from deepeval import evaluate
    from deepeval.dataset import EvaluationDataset
    from deepeval.evaluate.configs import AsyncConfig, DisplayConfig, CacheConfig, ErrorConfig
    goldens, tests, measurements = build_cloud_payload(store, run_id)
    if not status['dataset_uploaded']:
        dataset = EvaluationDataset(goldens=goldens)
        dataset.push(alias=status['dataset_alias'], finalized=False)
        store.execute('UPDATE cloud_sync SET dataset_uploaded=1 WHERE run_id=?', (run_id,))
    names = sorted({name for metric in measurements.values() for name in metric})
    result = evaluate(test_cases=tests, metrics=[recorded_metric(n, measurements) for n in names],
                      identifier='E.V.O ' + run_id,
                      async_config=AsyncConfig(run_async=False),
                      cache_config=CacheConfig(use_cache=False, write_cache=False),
                      error_config=ErrorConfig(ignore_errors=True),
                      display_config=DisplayConfig(show_indicator=False, print_results=False, inspect_after_run=False))
    return result.confident_link


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    sync_run(Store(args.db), args.run)
