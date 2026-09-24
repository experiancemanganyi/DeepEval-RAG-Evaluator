import json
import pytest
from fastapi.testclient import TestClient
from evo_platform.connectors import make_connector, ConnectorError
from evo_platform.interview_api import InterviewAPIConnector
from evo_platform.server import create_app
from evo_platform.runner import run_batch
from evo_platform.evaluation import evaluate_output
from evo_platform.cloud import sync_run, build_cloud_payload, recorded_metric

QUESTION = 'What is the difference between an INNER JOIN and a LEFT JOIN in SQL?'
OPTIONS = {'domains':[{'DomainID':3,'DomainName':'Data Analytics'}], 'technologies':[{'TechnologyID':4,'TechnologyName':'SQL'}], 'proficiencies':[{'LevelRank':2,'ProficiencyLevelName':'Basic Meaning'}]}
CONFIG = {'url':'https://50.62.181.23:8501/', 'certificate_exception_origin':'https://50.62.181.23:8501', 'adapter':'interview_api','domain_id':3,'technology_ids':[4],'level_rank':2}

@pytest.fixture
def api_calls(monkeypatch):
    calls=[]
    def request(self, method, path, **kwargs):
        calls.append((method,path,kwargs))
        if path.startswith('/api/config-options'): return OPTIONS
        if path == '/api/start-session': return {'questions':[{'QuestionID':32,'QuestionText':QUESTION}]}
        if path == '/api/evaluate': return {'concept_evaluations':[{'text':'Matching rows','status':'Covered','level':2},{'text':'Advanced','status':'Not Covered','level':5}], 'sections':{'explained_well':['Correct']}}
        raise AssertionError(path)
    monkeypatch.setattr(InterviewAPIConnector,'request',request)
    return calls


def test_interview_exact_identity_and_contract(api_calls):
    connector=make_connector('api',CONFIG)
    records,totals=connector.catalog()
    assert totals is None and records[0]['question_id']=='32'
    snap={'external_id':'32','question':QUESTION,'technology_external_id':'4','content':json.dumps({'candidate_input':'JOIN answer'})}
    with pytest.raises(ConnectorError): connector.submit(snap,'key')
    connector.start_session(snap)
    actual=connector.submit(snap,'key')
    sent=api_calls[-1][2]['json']
    assert sent=={'question_id':32,'question_text':QUESTION,'user_answer':'JOIN answer','level_rank':2}
    assert actual['counts']['covered']==1 and actual['counts']['not covered']==0
    assert len(actual['concept_evaluations'])==2
    assert actual['question_id'] is None  # Never pretend the backend echoed an ID.
    with pytest.raises(ConnectorError): connector.submit(snap,'key')


def test_changed_question_never_submitted(api_calls):
    connector=make_connector('api',CONFIG)
    snap={'external_id':'32','question':'Different question','technology_external_id':'4'}
    with pytest.raises(ConnectorError): connector.start_session(snap)
    assert not any(path=='/api/evaluate' for _,path,_ in api_calls)


@pytest.fixture
def prepared(tmp_path,api_calls,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('CONFIDENT_API_KEY',raising=False)
    monkeypatch.delenv('CONFIDENT_AI_API_KEY',raising=False)
    app=create_app(tmp_path/'test.db')
    client=TestClient(app)
    client.post('/api/login',json={'name':'Test','surname':'User'})
    aid=client.post('/api/connections',json={'name':'Interview','kind':'api','config':CONFIG}).json()['id']
    response=client.post(f'/api/connections/{aid}/interview-setup',json={'domain_id':3,'technology_ids':[4],'level_rank':2})
    assert response.status_code==200,response.text
    response=client.post(f'/api/connections/{aid}/interview-first-test')
    assert response.status_code==200,response.text
    return client,app.state.store,aid,response.json()


def test_first_test_waits_for_key_and_preserves_reference_review(prepared,api_calls):
    client,store,aid,result=prepared
    assert not result['started']
    snap=json.loads(store.results(result['run_id'])[0]['snapshot'])
    assert snap['reference']['validation']=='unverified'
    assert not any(path=='/api/evaluate' for _,path,_ in api_calls)
    config=json.loads(store.rows('SELECT config FROM runs')[0]['config'])
    assert 'Hallucination' in config['metrics']


def test_feedback_hallucination_requires_approved_reference():
    result=evaluate_output({'content':'{"candidate_input":"a"}','reference':None}, {'output':'text'}, {'metrics':['Feedback hallucination']})
    assert result['Feedback hallucination']['status']=='unavailable'


def test_full_capture_offline_judge_and_cloud_payload(prepared,monkeypatch):
    client,store,aid,result=prepared
    rid=result['run_id']
    def evaluator(snapshot,actual,config):
        assert actual['request_question_id']=='32'
        return {'Feedback accuracy':{'score':.8,'threshold':.5,'status':'passed','reason':'Fixture judgment'}}
    run_batch(store,rid,evaluator=evaluator)
    rows=store.results(rid)
    assert rows[0]['state']=='passed'
    assert store.rows('SELECT state FROM cloud_sync')[0]['state']=='waiting_for_key'
    goldens,tests,measurements=build_cloud_payload(store,rid)
    assert goldens[0].additional_metadata['approved_reference'] is None
    assert tests[0].additional_metadata['captured_response']['counts']['covered']==1
    metric=recorded_metric('Feedback accuracy',measurements)
    assert metric.measure(tests[0])==.8 and metric.is_successful()
    monkeypatch.setenv('CONFIDENT_API_KEY','fake-offline-test')
    sync_run(store,rid,publisher=lambda *args:'https://app.confident-ai.com/test-report')
    assert store.rows('SELECT state FROM cloud_sync')[0]['state']=='completed'
    sync_run(store,rid,publisher=lambda *args:pytest.fail('Completed uploads must not repeat'))


def test_cloud_unavailable_and_lower_is_better():
    from deepeval.test_case import LLMTestCase
    test=LLMTestCase(input='x',actual_output='y',name='id')
    metric=recorded_metric('Hallucination',{'id':{'Hallucination':{'score':.1,'threshold':.5,'status':'passed'}}})
    assert metric.measure(test)==.1 and metric.is_successful()
    with pytest.raises(ValueError): recorded_metric('Missing',{'id':{}}).measure(test)


def test_confident_key_is_never_returned(prepared):
    client,_,_,_=prepared
    client.post('/api/settings',json={'confident_key':'private-cloud-test-key'})
    response=client.get('/api/settings')
    assert response.json()['confident_configured']
    assert 'private-cloud-test-key' not in response.text
    client.post('/api/settings',json={'confident_key':''})
    assert client.get('/api/settings').json()['confident_configured']

def test_recorded_results_use_real_deepeval_without_rejudging(monkeypatch):
    from deepeval import evaluate
    from deepeval.test_case import LLMTestCase
    from deepeval.evaluate.configs import AsyncConfig, DisplayConfig, CacheConfig, ErrorConfig
    monkeypatch.delenv('CONFIDENT_API_KEY',raising=False)
    test=LLMTestCase(input='Question and answer',actual_output='Coaching report',name='saved-case')
    metrics={'saved-case':{'Feedback hallucination':{'score':.1,'threshold':.5,'status':'passed','reason':'Saved reason'}}}
    result=evaluate(test_cases=[test],metrics=[recorded_metric('Feedback hallucination',metrics)],
        async_config=AsyncConfig(run_async=False),cache_config=CacheConfig(use_cache=False,write_cache=False),
        error_config=ErrorConfig(ignore_errors=True),display_config=DisplayConfig(show_indicator=False,print_results=False,inspect_after_run=False))
    data=result.test_results[0].metrics_data[0]
    assert data.score==.1 and data.success is True and data.reason=='Saved reason'

