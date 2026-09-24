import threading
import time
import pytest
from fastapi.testclient import TestClient
from evo_platform.server import create_app

@pytest.fixture
def workspace(tmp_path):
    app=create_app(tmp_path/'test.db')
    client=TestClient(app)
    actor=client.post('/api/login',json={'name':'Alex','surname':'Smith'}).json()['user']
    store=app.state.store
    aid=store.save_application('Test','import',{})
    store.import_catalog(aid,[{'question':'One?','technology':'Tool'},{'question':'Two?','technology':'Tool'}])
    refs=[store.reference(q['id']) for q in store.questions(aid)]
    return client,store,aid,refs,actor

def finished(client,jid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        row=next(j for j in client.get('/api/jobs').json() if j['id']==jid)
        if row['state'] in ('completed','failed'):return row
        time.sleep(.01)
    pytest.fail('Background proposal job did not finish')

def test_users_add_edit_and_stable_identity(workspace):
    c,store,_,_,actor=workspace
    response=c.post('/api/users',json={'name':'Jane','surname':'Doe'})
    assert response.status_code==200
    uid=response.json()['id']
    assert len(c.get('/api/users').json())==2
    assert c.post('/api/users',json={'name':'jane','surname':'doe'}).status_code==409
    assert c.put('/api/users/'+uid,json={'name':'Janet','surname':'Doe'}).status_code==200
    assert c.put('/api/users/'+uid,json={'name':'Alex','surname':'Smith'}).status_code==409
    assert c.put('/api/users/'+actor['id'],json={'name':'Alexander','surname':'Smith'}).status_code==200
    assert c.get('/api/session').json()['user']['name']=='Alexander'
    logs=c.get('/api/activity').json()
    assert any(r['actor']=='Alex Smith' and r['action']=='ADD_USER' for r in logs)
    assert c.post('/api/users',json={'name':'','surname':'Doe'}).status_code==422

def test_bulk_proposals_then_approval(workspace,monkeypatch):
    c,store,aid,refs,_=workspace
    c.post('/api/settings',json={'openai_key':'fixture-only'})
    monkeypatch.setattr('evo_platform.server.propose_reference',lambda question,*args:{'expected_answer':'Answer to '+question,'concepts':['Concept']})
    response=c.post('/api/references/bulk-generate',json={'application_id':aid,'chunk_ids':[r['id'] for r in refs]})
    assert response.status_code==200,response.text
    job=finished(c,response.json()['job_id'])
    assert job['state']=='completed'
    latest=[store.reference(r['question_id']) for r in refs]
    assert all(r['validation']=='generated' for r in latest)
    body={'application_id':aid,'chunk_ids':[r['id'] for r in latest]}
    assert c.post('/api/references/bulk-approve',json=body).status_code==422
    response=c.post('/api/references/bulk-approve',json={**body,'reviewed':True})
    assert response.status_code==200
    assert all(store.reference(r['question_id'])['validation']=='approved' for r in refs)
    assert len(store.rows('SELECT * FROM chunks'))==6
    assert any(r['action']=='APPROVE_REFERENCE' for r in c.get('/api/activity').json())

def test_bulk_approval_atomic_stale_and_empty(workspace):
    c,store,aid,refs,_=workspace
    assert c.post('/api/references/bulk-approve',json={'application_id':aid,'chunk_ids':[refs[0]['id']],'reviewed':True}).status_code==422
    ids=[store.revise_chunk(r['id'],{'expected_answer':'Reviewed answer'}) for r in refs]
    store.revise_chunk(ids[1],{'expected_answer':'Newer draft'})
    before=len(store.rows('SELECT * FROM chunks'))
    response=c.post('/api/references/bulk-approve',json={'application_id':aid,'chunk_ids':ids,'reviewed':True})
    assert response.status_code==422
    assert len(store.rows('SELECT * FROM chunks'))==before
    assert store.reference(refs[0]['question_id'])['validation']=='unverified'

def test_bulk_generation_preserves_partial_success(workspace,monkeypatch):
    c,store,aid,refs,_=workspace
    c.post('/api/settings',json={'openai_key':'fixture'})
    def propose(question,*args):
        if question=='Two?':raise RuntimeError('sensitive provider error')
        return {'expected_answer':'Answer'}
    monkeypatch.setattr('evo_platform.server.propose_reference',propose)
    jid=c.post('/api/references/bulk-generate',json={'application_id':aid,'chunk_ids':[r['id'] for r in refs]}).json()['job_id']
    job=finished(c,jid)
    assert '1 proposals saved; 1 failed' in job['message']
    assert len(job['result']['generated'])==1 and len(job['result']['errors'])==1
    assert 'sensitive' not in str(job)

def test_bulk_generation_does_not_overwrite_concurrent_review(workspace,monkeypatch):
    c,store,aid,refs,_=workspace
    c.post('/api/settings',json={'openai_key':'fixture'})
    started,release=threading.Event(),threading.Event()
    def propose(*args):
        started.set();assert release.wait(5)
        return {'expected_answer':'Generated'}
    monkeypatch.setattr('evo_platform.server.propose_reference',propose)
    jid=c.post('/api/references/bulk-generate',json={'application_id':aid,'chunk_ids':[refs[0]['id']]}).json()['job_id']
    assert started.wait(2)
    revised=store.revise_chunk(refs[0]['id'],{'expected_answer':'Human revision'},'approved')
    release.set()
    job=finished(c,jid)
    assert len(job['result']['errors'])==1
    assert store.reference(refs[0]['question_id'])['id']==revised
