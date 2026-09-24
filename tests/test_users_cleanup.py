import json
from fastapi.testclient import TestClient
from evo_platform.server import create_app
from evo_platform.runner import worker_lock


def test_sign_in_required_logout_and_activity(tmp_path):
    app = create_app(tmp_path / 'test.db')
    client = TestClient(app)
    assert client.get('/api/bootstrap').status_code == 401
    assert client.post('/api/connections', json={}).status_code == 401
    assert client.get('/api/session').json()['user'] is None
    assert client.post('/api/login', json={'name': '', 'surname': 'Doe'}).status_code == 422
    response = client.post('/api/login', json={'name': 'Jane', 'surname': 'Doe'})
    user = response.json()['user']
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/session').json()['user']['surname'] == 'Doe'
    assert client.get('/api/bootstrap').status_code == 200
    client.post('/api/settings', json={'openai_key': 'never-log-this-value'})
    events = client.get('/api/activity').json()
    assert any(e['target'] == '/api/settings' and e['actor'] == 'Jane Doe' for e in events)
    assert 'never-log-this-value' not in json.dumps(events)
    assert client.post('/api/logout').status_code == 200
    assert client.get('/api/bootstrap').status_code == 401
    assert client.post('/api/login', json={'name': 'jane', 'surname': 'doe'}).json()['user']['id'] == user['id']


def test_cleanup_preserves_history_and_rejects_active_runs(tmp_path):
    app = create_app(tmp_path / 'test.db')
    client = TestClient(app)
    client.post('/api/login', json={'name': 'Alex', 'surname': 'Smith'})
    store = app.state.store
    aid = store.save_application('Offline', 'import', {})
    store.import_catalog(aid, [{'question': 'Question', 'technology': 'Tool'}])
    q = store.questions(aid)[0]
    did = store.create_dataset(aid, 'Unwanted', [{'question_id': q['id'], 'candidate_input': 'Answer'}])
    cid = store.rows('SELECT id FROM cases WHERE dataset_id=?', (did,))[0]['id']
    rid = store.create_run(aid, [cid], {'metrics': ['JSON output']})
    store.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
    assert client.delete('/api/datasets/' + did).status_code == 409
    assert client.delete('/api/runs/' + rid).status_code == 409
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
    with worker_lock(store, rid):
        assert client.delete('/api/runs/' + rid).status_code == 409
    assert client.delete('/api/runs/' + rid).status_code == 200
    assert client.get('/api/runs').json() == []
    assert client.delete('/api/datasets/' + did).status_code == 200
    assert client.get('/api/datasets/' + aid).json() == []
    assert client.get('/api/dataset/' + did + '/cases').status_code == 404
    assert len(store.results(rid)) == 1
    assert client.post('/api/runs', json={'application_id': aid, 'case_ids': [cid], 'config': {'metrics': ['JSON output']}, 'start': False}).status_code == 422
    assert any(e['action'] == 'DELETE' and e['actor'] == 'Alex Smith' for e in client.get('/api/activity').json())


def test_session_expiry_and_cross_origin_login(tmp_path):
    app = create_app(tmp_path / 'test.db')
    client = TestClient(app)
    assert client.post('/api/login', json={'name':'A','surname':'B'}, headers={'origin':'https://elsewhere.example'}).status_code == 403
    client.post('/api/login', json={'name':'A','surname':'B'})
    app.state.store.execute('UPDATE user_sessions SET expires_at=0')
    assert client.get('/api/bootstrap').status_code == 401
