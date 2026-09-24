import json
import threading
import pytest
from fastapi.testclient import TestClient
from test_bulk_users import workspace, finished


def case_setup(workspace):
    c, store, aid, refs, _ = workspace
    for ref in refs:
        store.revise_chunk(ref['id'], {'expected_answer': 'Reference answer'}, validation='approved')
    did = store.create_dataset(aid, 'Cases', [{'question_id': r['question_id'], 'candidate_input': 'Candidate answer'} for r in refs])
    cases = c.get('/api/dataset/'+did+'/cases').json()
    return did, [{'id': row['id'], 'content': row['content']} for row in cases]


def test_remove_restore_user_and_sessions(workspace):
    c, store, _, _, actor = workspace
    other = TestClient(c.app)
    user = other.post('/api/login', json={'name':'Jane', 'surname':'Doe'}).json()['user']
    assert c.delete('/api/users/'+actor['id']).status_code == 409
    assert c.delete('/api/users/'+user['id']).status_code == 200
    assert other.get('/api/bootstrap').status_code == 401
    assert other.post('/api/login', json={'name':' jane ', 'surname':'DOE'}).status_code == 422
    assert c.post('/api/users', json={'name':'Jane', 'surname':'Doe'}).status_code == 409
    assert len(store.rows('SELECT * FROM users')) == 2
    assert c.post('/api/users/'+user['id']+'/restore').status_code == 200
    assert other.post('/api/login', json={'name':'jane', 'surname':'doe'}).json()['user']['id'] == user['id']


def test_remove_completed_run_and_app_keeps_history(workspace):
    c, store, aid, _, _ = workspace
    did, items = case_setup(workspace)
    rid = store.create_run(aid, [items[0]['id']], {'metrics':['JSON output']})
    assert c.delete('/api/connections/'+aid).status_code == 409
    store.execute("UPDATE runs SET status='completed' WHERE id=?", (rid,))
    assert c.delete('/api/runs/'+rid).status_code == 200
    assert c.get('/api/runs').json() == []
    assert c.delete('/api/connections/'+aid).status_code == 200
    assert c.get('/api/bootstrap').json()['applications'] == []
    assert len(store.results(rid)) == 1
    with pytest.raises(ValueError):
        store.create_run(aid, [items[0]['id']], {'metrics':['JSON output']})


def test_bulk_case_proposals_and_approval_preserve_ids_snapshot(workspace, monkeypatch):
    c, store, aid, _, _ = workspace
    did, items = case_setup(workspace)
    rid = store.create_run(aid, [items[0]['id']], {'metrics':['JSON output']})
    snapshot = store.results(rid)[0]['snapshot']
    c.post('/api/settings', json={'openai_key':'fixture-only'})
    monkeypatch.setattr('evo_platform.evaluation.propose_case_expectation', lambda *args: 'Expected coaching feedback')
    response = c.post('/api/case-actions/generate', json={'dataset_id':did, 'items':items})
    assert response.status_code == 200, response.text
    assert finished(c, response.json()['job_id'])['state'] == 'completed'
    updated = c.get('/api/dataset/'+did+'/cases').json()
    assert {r['id'] for r in updated} == {r['id'] for r in items}
    assert all(r['validation']=='generated' and r['content']['expected_output']=='Expected coaching feedback' for r in updated)
    body = {'dataset_id':did, 'items':[{'id':r['id'], 'content':r['content']} for r in updated]}
    assert c.post('/api/case-actions/approve', json=body).status_code == 422
    assert c.post('/api/case-actions/approve', json={**body,'reviewed':True}).status_code == 200
    assert all(r['validation']=='approved' for r in c.get('/api/dataset/'+did+'/cases').json())
    assert store.results(rid)[0]['snapshot'] == snapshot
    assert c.post('/api/case-actions/approve', json={**body,'reviewed':True}).status_code == 409


def test_bulk_case_generation_does_not_overwrite_concurrent_review(workspace, monkeypatch):
    c, store, _, _, _ = workspace
    did, items = case_setup(workspace)
    c.post('/api/settings', json={'openai_key':'fixture-only'})
    started, release = threading.Event(), threading.Event()
    def proposal(*args):
        started.set()
        assert release.wait(5)
        return 'Generated expectation'
    monkeypatch.setattr('evo_platform.evaluation.propose_case_expectation', proposal)
    response = c.post('/api/case-actions/generate', json={'dataset_id':did,'items':items[:1]})
    assert started.wait(5)
    changed = {**items[0]['content'], 'expected_output':'Human reviewed expectation'}
    try:
        assert c.post('/api/cases/'+items[0]['id'], json={'content':changed,'approved':True}).status_code == 200
    finally:
        release.set()
    job = finished(c, response.json()['job_id'])
    assert '0 case proposals saved; 1 failed' in job['message']
    row = store.rows('SELECT * FROM cases WHERE id=?', (items[0]['id'],))[0]
    assert row['validation']=='approved'
    assert json.loads(row['content'])==changed
    assert c.post('/api/case-actions/approve', json={'dataset_id':did,'items':items,'reviewed':True}).status_code == 409
