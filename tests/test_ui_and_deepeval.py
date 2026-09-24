import json
import os
from pathlib import Path
import pytest

os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
ROOT = Path(__file__).resolve().parents[1]


def test_all_navigation_pages(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EVO_DB_PATH', str(tmp_path / 'ui.sqlite3'))
    app = AppTest.from_file(str(ROOT / 'EVO.py')).run(timeout=180)
    assert not app.exception
    for page in app.radio[0].options:
        app.radio[0].set_value(page).run(timeout=45)
        assert not app.exception, (page, [e.message for e in app.exception])


def test_deepeval_geval_with_offline_judge():
    """Executes real GEval orchestration; scripted judge makes no paid calls."""
    from deepeval.models import DeepEvalBaseLLM
    from evo_platform.evaluation import evaluate_output
    class ScriptedJudge(DeepEvalBaseLLM):
        def __init__(self):
            self.model_name = 'offline-test-judge'
        def load_model(self):
            return self
        def get_model_name(self):
            return self.model_name
        def generate(self, prompt, schema=None, **kwargs):
            data = {'steps': ['Compare candidate answer and feedback'], 'score': 10, 'reason': 'Controlled fixture agrees'}
            if schema:
                return schema(**data)
            return json.dumps(data)
        async def a_generate(self, prompt, schema=None, **kwargs):
            return self.generate(prompt, schema, **kwargs)
    snapshot = {'question': 'Explain one', 'content': json.dumps({'candidate_input': 'One'}), 'reference': None, 'validation': 'unverified'}
    results = evaluate_output(snapshot, {'output': 'Feedback for one'}, {'metrics': ['Feedback accuracy']}, judge=ScriptedJudge())
    assert results['Feedback accuracy']['score'] == 1
    assert results['Feedback accuracy']['status'] == 'passed'


def test_existing_rag_metric_exports():
    from deepeval import metrics
    for name in ('AnswerRelevancyMetric', 'FaithfulnessMetric', 'HallucinationMetric', 'ContextualRelevancyMetric', 'ContextualPrecisionMetric', 'ContextualRecallMetric', 'BiasMetric', 'ToxicityMetric'):
        assert getattr(metrics, name)
