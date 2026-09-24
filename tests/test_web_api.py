import json
import pytest
from fastapi.testclient import TestClient
from evo_platform.server import create_app
from evo_platform.runner import run_batch
from evo_platform.store import uid, encode


@pytest.fixture
def web(tmp_path):
    app = create_app(tmp_path / 'web.sqlite3')
    with TestClient(app) as client:
        assert client.post('/api/login',json={'name':'Test','surname':'User'}).status_code == 200
        yield client, app.state.store


def connected(client):
    response = client.post('/api/connections', json={'name': 'Synthetic regression', 'kind': 'import', 'config': {}})
    assert response.status_code == 200
    app_id = response.json()['id']
    response = client.post(f'/api/catalog/{app_id}/import', json={'records': [{'technology': 'Test technology', 'question_id': 'external-q1', 'question': 'Synthetic question?', 'concepts': ['Fixture concept']}]})
    assert response.status_code == 200
    question = client.get(f'/api/catalog/{app_id}').json()['questions'][0]
    return app_id, question


def test_web_serves_without_streamlit(web):
    client, _ = web
    assert client.get('/api/health').json()['interface'] == 'web'
    page = client.get('/')
    assert page.status_code == 200 and '/assets/app.js' in page.text
    assert 'streamlit' not in page.text.lower()
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/assets/styles.css').status_code == 200


def test_api_full_offline_evaluation_workflow(web):
    client, store = web
    app_id, question = connected(client)
    chunk = client.get('/api/chunks', params={'app_id': app_id}).json()[0]
    response = client.post(f"/api/chunks/{chunk['id']}/version", json={'content': chunk['content'], 'validation': 'approved'})
    assert response.status_code == 200
    case = {'question_id': question['id'], 'candidate_input': 'Fixture answer', 'score_range': [7, 9], 'actual': {'output': 'Fixture feedback', 'score': 8}}
    did = client.post(f'/api/datasets/{app_id}/import', json={'name': 'Review', 'cases': [case]}).json()['id']
    saved = client.get(f'/api/dataset/{did}/cases').json()[0]
    assert saved['validation'] == 'unverified'
    assert client.post(f"/api/cases/{saved['id']}", json={'content': saved['content'], 'approved': True}).status_code == 200
    rid = client.post('/api/runs', json={'application_id': app_id, 'case_ids': [saved['id']], 'config': {'metrics': ['Score accuracy'], 'interval': 0}, 'start': False}).json()['id']
    run_batch(store, rid)
    results = client.get(f'/api/runs/{rid}/results').json()
    assert results[0]['state'] == 'passed'
    assert results[0]['actual']['score'] == 8
    assert results[0]['metrics']['Score accuracy']['score'] == 1
    assert client.get('/api/dashboard').json()['tested_questions'] == 1
    assert client.get(f'/api/runs/{rid}/export?format=json').json()[0]['state'] == 'passed'
    assert 'text/csv' in client.get(f'/api/runs/{rid}/export?format=csv').headers['content-type']
    assert client.get(f'/api/runs/{rid}/export?format=pdf').content.startswith(b'%PDF')
    assert client.get(f'/api/runs/{rid}/export?format=docx').content.startswith(b'PK')


def test_web_security_and_secret_redaction(web):
    client, _ = web
    response = client.post('/api/settings', json={'openai_key': 'fixture-secret', 'judge_model': 'fixture-model'})
    assert response.status_code == 200
    result = client.get('/api/settings')
    assert 'fixture-secret' not in result.text and result.json()['openai_configured']
    assert client.post('/api/settings', json={}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.get('/api/health', headers={'Host': 'untrusted.example'}).status_code == 400
    assert client.post('/api/connections', json={'name': 'Bad', 'kind': 'api', 'config': {'url': 'https://example.com', 'token': 'fixture-secret'}}).status_code == 422


def test_document_upload_persistence_and_boundaries(web):
    client, store = web
    result = client.post('/api/rag/upload', files={'file': ('sample.txt', b'one two three four five', 'text/plain')}, data={'chunk_size': '3', 'overlap': '1'})
    assert result.status_code == 200 and result.json()['chunks'] == 3
    data = client.get('/api/rag').json()
    assert data['documents'][0]['name'] == 'sample.txt'
    assert data['documents'][0]['chunks'] == 3
    assert len(client.get('/api/chunks?kind=document').json()) == 3
    invalid = client.post('/api/rag/upload', files={'file': ('sample.txt', b'x', 'text/plain')}, data={'chunk_size': '3', 'overlap': '3'})
    assert invalid.status_code == 422
    assert client.post('/api/rag/upload', files={'file': ('script.exe', b'x')}).status_code == 422


def test_csv_import_parser(web):
    client, _ = web
    result = client.post('/api/imports/parse', files={'file': ('questions.csv', b'technology,question\nT,"Question, with comma"')})
    assert result.json()[0]['question'] == 'Question, with comma'


def test_rag_snapshot_review_preserves_previous_version(web):
    client, store = web
    sid = uid()
    store.execute('INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES(?,?,?,?)', (sid, 'Fixture', encode([{'question': 'Q', 'expected': 'A'}]), '{}'))
    response = client.post('/api/rag/snapshots/' + sid, json={'goldens': [{'question': 'Q', 'expected': 'Reviewed'}]})
    assert response.status_code == 200
    assert response.json()['id'] != sid
    assert len(client.get('/api/rag').json()['snapshots']) == 2


def test_connection_diagnostics_import_and_invalid_run(web):
    client, _ = web
    app_id, _ = connected(client)
    assert client.post(f'/api/connections/{app_id}/diagnostics', json={}).status_code == 200
    assert client.post('/api/runs', json={'application_id': app_id, 'case_ids': [], 'config': {'metrics': []}, 'start': False}).status_code == 422
    assert client.get('/api/runs/absent/export').status_code == 404


def test_question_reference_cannot_be_changed_by_case_edit(web):
    client, _ = web
    app_id, question = connected(client)
    did = client.post(f'/api/datasets/{app_id}/import', json={'name': 'Test', 'cases': [{'question_id': question['id'], 'candidate_input': ''}]}).json()['id']
    case = client.get(f'/api/dataset/{did}/cases').json()[0]
    response = client.post(f"/api/cases/{case['id']}", json={'content': {'question_id': 'different', 'candidate_input': ''}})
    assert response.status_code == 422


def test_simple_api_connection_keeps_token_out_of_database(web):
    client, store = web
    response = client.post('/api/connections', json={'name': 'Simple API', 'kind': 'api', 'config': {'url': 'https://example.com/evaluate'}, 'api_token': 'fixture-api-token'})
    assert response.status_code == 200
    row = store.rows('SELECT * FROM applications WHERE id=?', (response.json()['id'],))[0]
    assert 'fixture-api-token' not in row['config']
    config = json.loads(row['config'])
    assert config['url'] == 'https://example.com'
    assert config['submit_path'] == '/evaluate'
    assert config['token_env'].startswith('EVO_API_TOKEN_')


def test_actual_background_worker(web):
    import time
    client, store = web
    app_id, question = connected(client)
    did = client.post(f'/api/datasets/{app_id}/import', json={'name': 'Worker fixture', 'cases': [{'question_id': question['id'], 'candidate_input': 'Test', 'actual': {'output': '{}'}}]}).json()['id']
    case_id = client.get(f'/api/dataset/{did}/cases').json()[0]['id']
    response = client.post('/api/runs', json={'application_id': app_id, 'case_ids': [case_id], 'config': {'metrics': ['JSON output'], 'interval': 0}, 'start': True})
    assert response.status_code == 200
    run_id = response.json()['id']
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        rows = client.get(f'/api/runs/{run_id}/results').json()
        if rows[0]['state'] == 'passed':
            break
        time.sleep(.1)
    assert rows[0]['state'] == 'passed'


def test_login_control_rejects_missing_session(web):
    client, _ = web
    app_id, _ = connected(client)
    assert client.post(f'/api/connections/{app_id}/login', json={}).status_code == 422
    assert client.post(f'/api/connections/{app_id}/login/complete', json={}).status_code == 409

def test_generation_error_identifies_unapproved_question(web):
    client, store = web
    app_id, question = connected(client)
    response = client.post(f'/api/datasets/{app_id}/generate', json={
        'name': 'Needs review', 'question_ids': [question['id']],
        'categories': ['Fully correct'], 'count': 1})
    assert response.status_code == 422
    assert question['text'] in response.json()['detail']
    assert 'tick the approval box' in response.json()['detail']
    assert not store.rows('SELECT * FROM jobs')
