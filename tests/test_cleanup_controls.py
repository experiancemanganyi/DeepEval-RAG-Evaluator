from test_bulk_users import workspace


def test_document_removal_protects_busy_jobs_and_keeps_snapshots(workspace):
    c, store, _, _, _ = workspace
    store.save_document_chunk('Source text', {'file_id':'doc', 'file_title':'Document.txt'})
    store.execute("INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES('snapshot','Saved','[]','{}')")
    store.execute("INSERT INTO jobs(id,kind,state,document_id) VALUES('busy','RAG golden synthesis','queued','doc')")
    assert c.delete('/api/rag/documents/doc').status_code == 409
    store.execute("UPDATE jobs SET state='completed' WHERE id='busy'")
    assert c.delete('/api/rag/documents/doc').status_code == 200
    assert c.get('/api/rag').json()['documents'] == []
    assert c.get('/api/chunks?kind=document').json() == []
    assert len(c.get('/api/rag').json()['snapshots']) == 1
    assert c.post('/api/rag/synthesize', json={'document_id':'doc'}).status_code == 422
    assert c.delete('/api/rag/documents/doc').status_code == 404
    store.save_document_chunk('Source text', {'file_id':'doc', 'file_title':'Document.txt'})
    assert c.get('/api/rag').json()['documents'][0]['chunks'] == 1


def test_dismiss_jobs_only_terminal_and_persistent(workspace):
    c, store, _, _, _ = workspace
    for state in ['queued','running','awaiting_login','completed','failed']:
        store.execute('INSERT INTO jobs(id,kind,state) VALUES(?,?,?)', (state,'Fixture',state))
    for state in ['queued','running','awaiting_login']:
        assert c.delete('/api/jobs/'+state).status_code == 409
    assert c.delete('/api/jobs/completed').status_code == 200
    assert c.delete('/api/jobs').json()['removed'] == 1
    assert {j['id'] for j in c.get('/api/jobs').json()} == {'queued','running','awaiting_login'}
    assert c.delete('/api/jobs').json()['removed'] == 0
    assert len(store.rows('SELECT * FROM jobs')) == 5


def test_dashboard_excludes_all_removed_app_contributions(workspace):
    c, store, aid, refs, _ = workspace
    did = store.create_dataset(aid,'Dataset',[{'question_id':refs[0]['question_id'],'candidate_input':'Answer'}])
    cid = store.rows('SELECT id FROM cases WHERE dataset_id=?',(did,))[0]['id']
    rid = store.create_run(aid,[cid],{'metrics':['JSON output']})
    store.execute("UPDATE runs SET status='completed' WHERE id=?",(rid,))
    store.execute('UPDATE results SET state=?,actual=?,metrics=? WHERE run_id=?',('failed','{"output":"Answer"}','{"Metric":{"score":0.2}}',rid))
    before = c.get('/api/dashboard').json()
    assert before['questions'] == 2 and before['tested_questions'] == 1
    assert before['average_quality'] == .2 and before['failed'] == 1
    assert c.delete('/api/connections/'+aid).status_code == 200
    after = c.get('/api/dashboard').json()
    for key in ['technologies','questions','tested_questions','pending','failed','errors']:
        assert after[key] == 0
    for key in ['runs','technologies_breakdown','states']:
        assert after[key] == []
    assert after['average_quality'] is None and after['candidate_score_accuracy'] is None
    assert len(store.results(rid)) == 1
    other = store.save_application('Still active','import',{})
    store.import_catalog(other,[{'question':'Visible question','technology':'Visible tech'}])
    assert c.get('/api/dashboard').json()['questions'] == 1
