# Automated AI Interview testing

## What changed

E.V.O now connects to the existing interview practice API. It does not modify the AI Interview server, its code, its questions, or its configuration. This tests the interview evaluation backend; it does not test microphone recording, browser rendering, or click navigation.

The website's publicly served client identifies these same-origin endpoints:
- GET /api/config-options: available domains, technologies, and levels.
- POST /api/start-session: questions for the selected practice configuration.
- POST /api/evaluate: question_id, question_text, user_answer, and level_rank; returns coaching sections and concept evaluations.

The first two endpoints were reached successfully on the real server. SQL returned question 19 (query optimization) and question 32 (INNER/LEFT JOIN). No automated answer submission or paid model evaluation was performed during this update; the user will supply keys later.

## First test — simple steps

1. Restart your local E.V.O server. In its PowerShell terminal press Ctrl+C, then run .\Start-EVO.ps1 from C:\Users\Admin\source\repos\DeepEval-RAG-Evaluator. Refresh http://127.0.0.1:8080.
2. Open Applications → AI Interview Tool → Interview automation.
3. Choose Technical → Data Analytics → SQL → Basic Meaning. Click Save & collect questions. This fetches session questions without submitting answers.
4. Open Reference library, select AI Interview Tool, and review the JOIN question. A locally authored starter answer/concepts are provided. Correct them if needed, tick approval, and Save new version. This is an independent reference, not an official server rubric.
5. When ready, open Settings and enter your OpenAI API key and Confident AI API key. Save. The first judges feedback; the second uploads datasets and results. Keys remain in server memory. For persistence set OPENAI_API_KEY and CONFIDENT_API_KEY in your local environment before starting; never commit keys.
6. Applications → AI Interview Tool → First automated test. It creates one SQL JOIN test and runs it automatically when the judge key is present. If the key is absent, it prepares a pending run without sending an answer. After adding the key, use Test runs → Resume.
7. Open Results → select the run → Inspect. For cloud progress, Test runs → Confident AI. A completed upload has an Open cloud report link.

Approve references BEFORE creating a run: each run keeps an immutable snapshot. Approving a reference later does not alter an existing pending run. Cancel the old pending run and create a fresh one if you need its reference changed.

## What runs automatically

E.V.O obtains live session questions and checks BOTH the stored question ID and text. If either differs, it stops before submitting. It sends the candidate answer once with that question and the selected proficiency level. It saves the returned report, concept labels, and counts, then DeepEval evaluates the saved output.

The starter test now selects the full real DeepEval suite: all eight original native metrics plus the applicable GEval and conversation checks. See UNIVERSAL_METRICS.md. JSON and numeric checks remain optional supplementary local checks. The hallucination check uses DeepEval HallucinationMetric with the question, submitted answer, and approved independent reference as context. Reference-dependent checks show unavailable without approval; missing evidence is never counted as a pass. Numeric candidate score is not invented from concept counts.

To use other questions or more answer types: collect questions, approve references, then Datasets → Generate test cases (requires OpenAI) or Import dataset. Review the generated cases. Test runs → New test run lets you select a dataset, cases, and metrics. Use RAG contextual metrics only when actual retrieval context is available; the interview API currently does not provide it. Session question lists are samples; the app does not claim complete catalog coverage.

## Confident AI

When a local run finishes, E.V.O pushes a per-run dataset and the measured results through the installed DeepEval SDK. The dataset uses alias evo-<local-run-id> and is left unfinalized for review. Metadata includes question identity, candidate answer, captured coaching output, review status, available approved reference, local metric details, and execution failures.

Cloud metric reporting replays the SAVED measurements through DeepEval's evaluation interface. It does not re-call the interview tool or spend another judge call. Scores, thresholds, pass/fail results, and reasons are preserved, including lower-is-better hallucination scores. Unavailable/error checks are reported as errors, not passing scores. The UI saves the cloud report link only if the SDK returns one.

If the key is missing, the sync status says waiting_for_key. Add the key and choose Sync to Confident AI. If cloud upload fails, local results remain. Retry sync only. A cloud timeout can leave an unconfirmed duplicate report; inspect the cloud dashboard before repeated retries.

See the official [DeepEval dataset documentation](https://deepeval.com/docs/evaluation-datasets) and [environment settings](https://deepeval.com/docs/environment-variables).

## Verification and limits

51 automated tests passed; one separately marked browser test was excluded because Playwright launch is blocked in this sandbox. Tests cover the actual API request contract using controlled responses, question mismatch rejection, no-key preparation, raw capture and counts, reference gating, cloud payloads/key redaction, and real DeepEval replay of measured results without a judge call. JavaScript syntax and Python compilation checks passed.

Real API configuration/question discovery succeeded. Live answer evaluation, paid judge quality, and actual Confident AI authentication/uploads still need the user's keys and a live test. The latest server could not be restarted here: automatic approval review rejected the process action. Restart it locally before using the new routes.

