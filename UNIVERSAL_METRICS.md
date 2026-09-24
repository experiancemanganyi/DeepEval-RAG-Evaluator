# Real DeepEval for every connected tool

E.V.O uses the installed DeepEval package to evaluate captured outputs from website, API, interview API, and imported-result connectors. The connector obtains the output; it does not decide the quality score.

## Native metric implementations

The full default suite includes all eight native metrics already present in the original project:

| Check | Actual implementation | Required evidence |
|---|---|---|
| Answer relevancy | deepeval.metrics.AnswerRelevancyMetric | Task input and actual output |
| Hallucination | deepeval.metrics.HallucinationMetric | Approved independent reference or reviewed case context |
| Bias | deepeval.metrics.BiasMetric | Actual output |
| Toxicity | deepeval.metrics.ToxicityMetric | Actual output |
| Faithfulness | deepeval.metrics.FaithfulnessMetric | Actual retrieval context |
| Contextual relevancy | deepeval.metrics.ContextualRelevancyMetric | Actual retrieval context |
| Contextual precision | deepeval.metrics.ContextualPrecisionMetric | Actual retrieval context and approved expected output |
| Contextual recall | deepeval.metrics.ContextualRecallMetric | Actual retrieval context and approved expected output |

Names no longer imply these checks only work with RAG. Contextual checks are available to any tool that supplies actual retrieval data. A tool that does not supply it gets unavailable for those checks, never a fabricated passing result. Historical RAG-prefixed run names still work.

The full suite also includes real DeepEval GEval checks for concept coverage, partial recognition, missed/incorrect concepts, feedback accuracy/completeness, technical/factual correctness, relevance, instruction adherence, manipulation resistance, and custom criteria. Conversation completeness uses ConversationCompletenessMetric when exported conversation turns are provided. Prerequisite checks apply to each metric.

Score ranges, exact concept labels, JSON syntax, and numeric consistency are clearly labelled local supplementary checks. They are not presented as native DeepEval metrics and are not selected by default in place of DeepEval.

## Running it

Restart local E.V.O, then open Test runs → New test run. Choose any connected application and dataset. The full DeepEval suite is selected by default. You can adjust selection for a targeted run. The AI Interview First automated test button now uses this same full suite.

Each result identifies the actual implementation, score, threshold, reason and status. Lower hallucination, bias and toxicity scores are better; aggregate quality accounts for that direction. A metric error does not discard successful checks or stop later metrics. Retry judge errors uses the previously captured answer instead of submitting it again.

DeepEval uses an LLM judge internally for many metrics. Providing an OpenAI key supplies that judge; the real DeepEval library still constructs test cases, runs the metric algorithms, and computes scores. No generic prompt substitutes for those metric implementations.

Confident AI receives the saved cases and measurements through the SDK upload path already implemented. It preserves scores and errors rather than generating fresh judgments during upload. Both live judging and cloud upload await the keys you said you will add later.

## Verification

All eight native classes were executed successfully on non-RAG fixture inputs using the actual installed DeepEval algorithms and an offline schema-aware judge. These tests make no paid calls and do not prove real judge accuracy. They also test missing evidence, independent metric errors, implementation metadata, and lower-is-better scores. See EVO-Validation.md for the complete test-suite result.

The AI Interview server code remains unchanged.
