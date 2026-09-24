"""Persistence and result compatibility for the existing RAG workflow."""
from .store import Store, encode, uid


def save_snapshot(label, goldens, metrics):
    Store().execute('INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES(?,?,?,?)', (uid(), label, encode(goldens), encode(metrics)))


def metric_scores(evaluation_result, test_cases):
    scores = {}
    # Current DeepEval returns metrics on EvaluationResult.test_results.
    for result in getattr(evaluation_result, 'test_results', []) or []:
        for metric in getattr(result, 'metrics_data', []) or []:
            name, score = getattr(metric, 'name', ''), getattr(metric, 'score', None)
            if name and score is not None:
                scores.setdefault(name.replace('Metric', ''), []).append(score)
    if scores:
        return scores
    # Preserve compatibility with historical metadata attached to test cases.
    for case in test_cases:
        for name, metric in (getattr(case, 'metrics_metadata', None) or {}).items():
            score = metric.get('score') if isinstance(metric, dict) else getattr(metric, 'score', None)
            if score is not None:
                scores.setdefault(name.replace('Metric', ''), []).append(score)
    return scores
