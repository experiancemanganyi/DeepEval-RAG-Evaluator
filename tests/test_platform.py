import json
import sqlite3
import pytest
from evo_platform.store import Store, parse_records
from evo_platform.connectors import validate_config, APIConnector, ImportedConnector, ConnectorError
from evo_platform.evaluation import evaluate_output, available, consistency
from evo_platform.runner import run_batch, recover


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'evaluation.sqlite3')
    app = store.save_application('Offline', 'import', {})
    store.import_catalog(app, [{'technology': 'One', 'question_id': '1', 'question': 'Explain one', 'concepts': ['A']}, {'technology': 'Two', 'question_id': '1', 'question': 'Explain two'}])
    q = store.questions(app)[0]
    return store, app, q


def prepared(setup, actual=None):
    store, app, q = setup
    did = store.create_dataset(app, 'Regression', [{'question_id': q['id'], 'candidate_input': 'A', 'score_range': [7, 9], 'actual': actual or {'output': 'Correct', 'score': 8}}])
    case = store.rows('SELECT * FROM cases WHERE dataset_id=?', (did,))[0]
    store.execute("UPDATE cases SET validation='approved' WHERE id=?", (case['id'],))
    rid = store.create_run(app, [case['id']], {'metrics': ['Score accuracy'], 'interval': 0})
    return store, rid


def test_migration_preserves_data(setup):
    store, app, q = setup
    again = Store(store.path)
    assert len(again.questions(app)) == 2
    assert len(again.rows('SELECT * FROM schema_migrations')) == 7
    with pytest.raises(sqlite3.IntegrityError):
        again.execute('INSERT INTO technologies(id,application_id,external_id,name) VALUES(?,?,?,?)', ('x', 'missing', 'x', 'x'))


def test_discovery_deduplication_and_coverage(setup):
    store, app, q = setup
    stats = store.import_catalog(app, [{'technology': 'One', 'question_id': '1', 'question': 'Explain one'}])
    assert stats['duplicates'] == 1
    assert stats['technologies']['One']['complete'] is False
    assert len(store.questions(app)) == 2
    assert not store.import_catalog(app, [], verified_totals={'one': 1})['technologies']['One']['complete']
    assert store.import_catalog(app, [{'technology': 'One', 'question_id': '1', 'question': 'Explain one'}], verified_totals={'one': 1})['technologies']['One']['complete']


def test_import_rollback_and_changed_identity(setup):
    store, app, q = setup
    with pytest.raises(ValueError):
        store.import_catalog(app, [{'technology': 'New', 'question': 'Added'}, {'question': 'Invalid'}])
    assert len(store.questions(app)) == 2
    with pytest.raises(ValueError):
        store.import_catalog(app, [{'technology': 'One', 'question_id': '1', 'question': 'Changed'}])


def test_reference_versions_do_not_overwrite(setup):
    store, app, q = setup
    old = store.reference(q['id'])
    new = store.revise_chunk(old['id'], {'concepts': ['Reviewed']}, 'approved')
    store.import_catalog(app, [{'technology': 'One', 'question_id': '1', 'question': 'Explain one', 'concepts': ['Untrusted']}])
    assert store.reference(q['id'])['id'] == new
    assert json.loads(store.rows('SELECT * FROM chunks WHERE id=?', (old['id'],))[0]['content'])['concepts'] == ['A']


def test_document_mirror_preserves_metadata(setup):
    store, _, _ = setup
    metadata = {'file_title': 'report', 'chunk_index': 0}
    store.save_document_chunk('abc', metadata)
    store.save_document_chunk('abc', metadata)
    chunks = store.rows("SELECT * FROM chunks WHERE kind='document'")
    assert len(chunks) == 1
    assert json.loads(chunks[0]['content'])['metadata'] == metadata


def test_complete_offline_run_and_exports(setup):
    store, rid = prepared(setup)
    run_batch(store, rid)
    result = store.results(rid)[0]
    assert result['state'] == 'passed'
    assert json.loads(result['actual'])['score'] == 8
    assert json.loads(result['metrics'])['Score accuracy']['score'] == 1
    assert json.loads(store.export_results(rid))[0]['id'] == result['id']
    assert 'candidate' in store.export_results(rid, 'csv')
    run_batch(store, rid)
    assert len(store.results(rid)) == 1


def test_unverified_scores_are_unavailable(setup):
    store, rid = prepared(setup)
    snap = json.loads(store.results(rid)[0]['snapshot'])
    snap['validation'] = 'unverified'
    assert not available('Score accuracy', snap, {})[0]
    assert evaluate_output(snap, {'score': 8}, {'metrics': ['Score accuracy']})['Score accuracy']['status'] == 'unavailable'


def test_dataset_snapshots_and_cross_application(setup):
    store, rid = prepared(setup)
    row = store.results(rid)[0]
    store.execute("UPDATE cases SET content='{}' WHERE id=?", (row['case_id'],))
    run_batch(store, rid)
    assert store.results(rid)[0]['state'] == 'passed'
    other = store.save_application('Other', 'import', {})
    with pytest.raises(ValueError):
        store.create_run(other, [row['case_id']], {})


def test_ambiguous_submit_never_retried(setup):
    store, rid = prepared(setup)
    class Broken(ImportedConnector):
        calls = 0
        def submit(self, snapshot, key):
            Broken.calls += 1
            raise TimeoutError('Secret that must not be saved')
    run_batch(store, rid, lambda *args: Broken({}))
    assert store.results(rid)[0]['state'] == 'needs_review'
    recover(store, rid)
    run_batch(store, rid, lambda *args: Broken({}))
    assert Broken.calls == 1
    assert 'Secret' not in store.results(rid)[0]['error']


def test_captured_output_recovery_does_not_submit(setup):
    store, rid = prepared(setup)
    store.execute("UPDATE results SET state='captured',actual=? WHERE run_id=?", ('{"score":8,"output":"Done"}', rid))
    class NoSubmit(ImportedConnector):
        def submit(self, *args):
            pytest.fail('Captured result must not resubmit')
    run_batch(store, rid, lambda *args: NoSubmit({}))
    assert store.results(rid)[0]['state'] == 'passed'


def test_cancel_and_worker_exclusion(setup):
    store, rid = prepared(setup)
    store.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
    run_batch(store, rid)
    assert store.results(rid)[0]['state'] == 'pending'
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
    run_batch(store, rid)
    assert store.results(rid)[0]['state'] == 'pending'


def test_api_catalog_pagination():
    api = APIConnector({'url': 'https://example.com', 'catalog_path': 'catalog'})
    pages = {'catalog': {'questions': [{'question': 'Q'}], 'next': 'page2'}, 'page2': {'questions': [{'question': 'R'}], 'totals': {'x': 2}}}
    api.request = lambda method, path: pages[path]
    rows, totals = api.catalog()
    assert len(rows) == 2 and totals == {'x': 2}


def test_security_and_tls_scope():
    with pytest.raises(ValueError):
        validate_config('api', {'url': 'https://example.com', 'token': 'secret'})
    with pytest.raises(ValueError):
        validate_config('browser', {'url': 'https://other.com', 'certificate_exception_origin': 'https://example.com'})
    validate_config('browser', {'url': 'https://example.com', 'certificate_exception_origin': 'https://example.com'})
    api = APIConnector({'url': 'https://example.com'})
    with pytest.raises(ConnectorError):
        api.request('GET', 'https://different.com')


def test_json_csv_import():
    assert parse_records('technology,question\nA,Q', 'a.csv')[0]['technology'] == 'A'
    with pytest.raises(ValueError):
        parse_records('{}', 'a.json')


def test_consistency():
    assert consistency([7, 8], 1)['status'] == 'passed'
    assert consistency([7], 1)['status'] == 'unavailable'


def test_existing_document_chunking():
    from processDocuments import DocumentProcessor
    chunks = DocumentProcessor(3, 1).chunk_text('a b c d e', 'sample.txt')
    assert [c['text'] for c in chunks] == ['a b c', 'c d e', 'e']
    with pytest.raises(ValueError):
        DocumentProcessor(3, 3)


def test_distinct_external_ids_with_identical_text(setup):
    store, app, _ = setup
    store.import_catalog(app, [{'technology': 'One', 'question_id': '2', 'question': 'Explain one'}])
    assert len(store.questions(app)) == 3


def test_technology_only_discovery(setup):
    store, app, _ = setup
    store.import_technologies(app, [{'id': 'new-id', 'name': 'New technology'}])
    store.import_technologies(app, [{'id': 'new-id', 'name': 'New technology'}])
    assert len(store.rows('SELECT * FROM technologies WHERE application_id=?', (app,))) == 3


def test_worker_lock_blocks_overlapping_recovery(setup):
    from evo_platform.runner import worker_lock
    store, rid = prepared(setup)
    with worker_lock(store, rid) as acquired:
        assert acquired
        with pytest.raises(ValueError):
            recover(store, rid)


def test_pause_and_resume_batch(setup):
    store, app, q = setup
    did = store.create_dataset(app, 'two', [{'question_id': q['id'], 'candidate_input': str(i), 'actual': {'output': '{}'}} for i in range(2)])
    ids = [c['id'] for c in store.rows('SELECT id FROM cases WHERE dataset_id=?', (did,))]
    rid = store.create_run(app, ids, {'metrics': ['JSON output'], 'batch_size': 1, 'interval': 0})
    run_batch(store, rid)
    assert [r['state'] for r in store.results(rid)] == ['passed', 'pending']
    assert store.rows('SELECT status FROM runs WHERE id=?', (rid,))[0]['status'] == 'paused'
    run_batch(store, rid)
    assert [r['state'] for r in store.results(rid)] == ['passed', 'passed']


def test_random_question_rematches_correct_answer(setup):
    from evo_platform.connectors import QuestionMismatch
    store, app, q = setup
    store.import_catalog(app, [{'technology': 'One', 'question_id': 'new', 'question': 'Another question'}])
    other = next(row for row in store.questions(app) if row['external_id'] == 'new')
    did = store.create_dataset(app, 'random', [{'question_id': question['id'], 'candidate_input': question['text'], 'actual': {'output': '{}'}} for question in (q, other)])
    ids = [c['id'] for c in store.rows('SELECT id FROM cases WHERE dataset_id=? ORDER BY rowid', (did,))]
    rid = store.create_run(app, ids, {'metrics': ['JSON output'], 'interval': 0})
    class RandomQuestion(ImportedConnector):
        def start_session(self, snapshot):
            raise QuestionMismatch('Another question', 'new')
        def submit(self, snapshot, key):
            assert json.loads(snapshot['content'])['candidate_input'] == 'Another question'
            return {'output': '{}'}
    run_batch(store, rid, lambda *args: RandomQuestion({}))
    rows = store.results(rid)
    assert rows[0]['state'] == 'pending'
    assert rows[1]['state'] == 'passed'


def test_candidate_generation_rejects_unreviewed_reference():
    from evo_platform.evaluation import generate_cases
    with pytest.raises(ValueError):
        generate_cases({}, {'validation': 'unverified'}, ['Empty'], 1, 'unused', 'unused')


def test_candidate_generation_validates_provider_output(monkeypatch):
    from types import SimpleNamespace
    from evo_platform.evaluation import generate_cases
    import openai
    answer = {'cases': [{'category': 'Empty', 'candidate_input': 'should be cleared', 'score_range': [0, 0]}]}
    completion = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion))))
    cases = generate_cases({'id': 'q', 'text': 'Q'}, {'validation': 'approved', 'content': '{}'}, ['Empty'], 1, 'test', 'test')
    assert cases[0]['candidate_input'] == '' and 'score_range' not in cases[0]


def test_rag_metric_result_compatibility():
    from types import SimpleNamespace
    from evo_platform.rag_bridge import metric_scores
    result = SimpleNamespace(test_results=[SimpleNamespace(metrics_data=[SimpleNamespace(name='Faithfulness', score=.8)])])
    assert metric_scores(result, []) == {'Faithfulness': [.8]}


def test_missing_rag_context_disables_metric():
    snap = {'content': '{"candidate_input":"Q"}', 'reference': None}
    metric = evaluate_output(snap, {'output': 'A'}, {'metrics': ['RAG faithfulness']})
    assert metric['RAG faithfulness']['status'] == 'unavailable'


def test_equivalent_answer_consistency_in_run(setup):
    store, app, question = setup
    ref = store.reference(question['id'])
    store.revise_chunk(ref['id'], json.loads(ref['content']), 'approved')
    did = store.create_dataset(app, 'Equivalent answers', [{'question_id': question['id'], 'candidate_input': answer, 'equivalence_group': 'same-concept', 'actual': {'output': 'Feedback', 'score': score}} for answer, score in [('Answer one', 8), ('Equivalent answer', 6)]])
    cases = store.rows('SELECT id FROM cases WHERE dataset_id=?', (did,))
    store.execute("UPDATE cases SET validation='approved' WHERE dataset_id=?", (did,))
    rid = store.create_run(app, [c['id'] for c in cases], {'metrics': ['Evaluation consistency'], 'interval': 0, 'consistency_tolerance': 1})
    run_batch(store, rid)
    assert all(row['state'] == 'failed' for row in store.results(rid))
    assert json.loads(store.results(rid)[0]['metrics'])['Evaluation consistency']['score'] == 0
