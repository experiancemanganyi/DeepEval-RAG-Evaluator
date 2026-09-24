import json
import pytest
from deepeval.models import DeepEvalBaseLLM
from evo_platform.evaluation import evaluate_output, NATIVE_METRICS, all_deepeval_metrics

class OfflineJudge(DeepEvalBaseLLM):
    def __init__(self): self.model_name='offline-schema-fixture'
    def load_model(self): return self
    def get_model_name(self): return self.model_name
    def generate(self,prompt,schema=None,**kwargs):
        data={'statements':['A relevant statement'],'claims':['A supported claim'],'truths':['A source fact'],
              'opinions':['An opinion'], 'verdicts':[{'verdict':'yes','reason':'Controlled fixture','statement':'A relevant statement'}],
              'reason':'Controlled fixture','score':10,'steps':['Compare input and output']}
        return schema(**data) if schema else json.dumps(data)
    async def a_generate(self,prompt,schema=None,**kwargs): return self.generate(prompt,schema,**kwargs)

@pytest.mark.parametrize('name',[n for n in NATIVE_METRICS if not n.startswith('RAG ')])
def test_real_native_deepeval_on_non_rag_tool(name):
    snapshot={'question':'Explain the tool task','validation':'approved','reference':None,
              'content':json.dumps({'candidate_input':'Input task','expected_output':'Expected tool output','context':['Trusted source fact']})}
    results=evaluate_output(snapshot,{'output':'A tool output','retrieval_context':['Actual retrieved source fact']},
                            {'metrics':[name]},judge=OfflineJudge())
    result=results[name]
    assert result['status'] in ('passed','failed'),result
    assert result['engine']=='DeepEval'
    assert result['implementation']=='deepeval.metrics.'+NATIVE_METRICS[name][0]
    assert 0 <= result['score'] <= 1
    if name in ('Hallucination','Bias','Toxicity'):
        assert result['higher_is_better'] is False
        assert result['quality_score']==1-result['score']


def test_all_metrics_keep_missing_data_explicit():
    snapshot={'question':'Question','validation':'unverified','reference':None,'content':'{"candidate_input":"Answer"}'}
    results=evaluate_output(snapshot,{'output':'Feedback'}, {'metrics':['Hallucination','Faithfulness','Contextual precision','Contextual recall']},judge=OfflineJudge())
    assert all(m['status']=='unavailable' for m in results.values())


def test_one_metric_failure_does_not_drop_other_checks(monkeypatch):
    import evo_platform.evaluation as module
    original=module._evaluate_output
    def one(snapshot,actual,config,judge):
        if config['metrics']==['Bias']: raise RuntimeError('provider secret should not appear')
        return original(snapshot,actual,config,judge)
    monkeypatch.setattr(module,'_evaluate_output',one)
    snapshot={'question':'Q','content':'{"candidate_input":"A"}'}
    results=evaluate_output(snapshot,{'output':'{}'}, {'metrics':['Bias','JSON output']})
    assert results['Bias']['status']=='error'
    assert 'secret' not in results['Bias']['reason']
    assert results['JSON output']['status']=='passed'
    assert results['JSON output']['engine']=='Local check'


def test_full_suite_contains_all_original_native_classes():
    assert {NATIVE_METRICS[n][0] for n in all_deepeval_metrics() if n in NATIVE_METRICS} == {
        'AnswerRelevancyMetric','FaithfulnessMetric','ContextualRelevancyMetric','ContextualPrecisionMetric',
        'ContextualRecallMetric','HallucinationMetric','BiasMetric','ToxicityMetric'}
