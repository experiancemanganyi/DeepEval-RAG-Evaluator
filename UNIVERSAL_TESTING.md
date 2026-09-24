# Architecture and technical configuration

## Project inspection and preservation

The existing project is Python. `EVO.py` contains the original Streamlit frontend and its RAG orchestration.
`processDocuments.py` extracts files, splits by word count/overlap, and uploads to Supabase.
`RAG_DeepEval.py`, `main.py`, and `Evaluate.py` provide the original CLI, synthesis, metrics, cloud integration, and reports.
No C# project or source solution was present outside Visual Studio's local `.vs` state.

The new default frontend is `web/index.html`, `web/styles.css`, and `web/app.js`.
`evo_platform/server.py` serves it and the API in the same process. No JavaScript build step is required.
`Start-EVO.ps1` starts Uvicorn on localhost:8080. It does not start Streamlit.
The legacy code is retained and its navigation regression-tested; it is not the new primary interface.

## Modules

| Module | Responsibility |
|---|---|
| `store.py` | Transactional SQLite persistence, immutable run snapshots, reference versions, import/export |
| `migrations/*.sql` | Versioned schema creation and RAG/job additions |
| `connectors.py` | Import, normalized API, generic browser, and guarded interview adapters |
| `runner.py` | Persistent run state, per-application locks, bounded connection retry, submission safety |
| `evaluation.py` | Reference-gated GEval, RAG and conversation metrics, deterministic checks, generation |
| `providers.py` | OpenAI judge wrapper with structured responses and bounded provider calls |
| `rag_bridge.py` | Original RAG checkpoint persistence and DeepEval result compatibility |
| `server.py` | Local API, credentials in memory, background workers/jobs, manual sign-in capture |
| `ui.py` | Compatibility extensions for the retained legacy Streamlit UI |

SQLite stores applications, technologies, questions, chunks, datasets, cases, runs, results, discovery statistics, RAG snapshots, and background jobs.
Structured chunk content holds concepts, alternative explanations, weights, rubric, maximum score, and source fields as available; missing fields are not invented.
Documents retain their metadata and parent relationships. Supabase data is not migrated destructively.
SQL Server/PostgreSQL adapters are not implemented for the new local persistence layer; existing Supabase remains independent.

## API connector contract

The simple connection UI accepts a full submission endpoint and optional bearer token.
The normalized POST body is:

```json
{"question_id":"external-id","question":"Question text","technology":"external-technology-id","answer":"Candidate answer"}
```

Expected response fields:

```json
{"output":"AI evaluation","score":8,"feedback":"Feedback","question_id":"external-id","concepts":{"concept-a":"covered"},"retrieval_context":["Retrieved passage"]}
```

Only the fields actually available are required by their selected metrics. `response_fields` maps canonical names to top-level response keys.
Configure `catalog_path` for authorized catalog discovery. Catalog responses may be arrays or:

```json
{"questions":[{"technology":"Example","technology_id":"example","question_id":"q1","question":"Question text"}],"next":"/catalog?page=2","totals":{"example":1}}
```

Pagination is bounded; repeated pages and cross-origin requests are rejected.
Completeness requires authoritative totals and a matching set of unique records collected during that full synchronization, not merely enough historical random observations.
Arbitrary API workflows require a dedicated adapter implementing the common connector interface.

## Browser connection options

Inspect the actual website before configuring selectors. `Check connection` lists visible control attributes without reading password values and suggests only unambiguous candidate controls. Confirm them before submission.

| Option | Meaning |
|---|---|
| `input`, `submit`, `response`, `completion` | Answer box, submission control, output area, fresh-completion signal |
| `question`, `question_id_attribute` | Exact displayed-question matching; external ID attribute if exposed |
| `technology_select`, `question_select` | Native select controls |
| `technology_open`, `technology_options` | Configured custom technology menu |
| `reset`, `start`, `next_question` | Application-specific session controls |
| `catalog_rows`, `catalog_fields`, `catalog_next` | Authorized catalog table and pagination mapping |
| `observation_sessions`, `max_questions_per_session`, `max_pages` | Bounded discovery limits |
| `timeout`, `browser_channel`, `headless` | Browser runtime settings |
| `storage_state_env` | Environment variable naming a local browser session file |
| `login` | Optional explicit selectors plus username/password environment-variable names |

An already-visible completion indicator is rejected to avoid stale result capture. Streaming applications need a reliable terminal signal.
The interview adapter requires a displayed-question selector and will not submit a mismatched answer. If a random question matches another unambiguous pending case in the same technology, the runner uses that matching case's snapshot. Unknown questions are never answered with another question's test input.
Observation discovery never claims database completeness. It does not submit dummy candidate answers just to advance an interview.
Audio-only interviews, virtualized controls, multi-step proprietary workflows, and administrator-only catalogs still need a site-specific adapter or export.

## Authentication and TLS

Website Sign in opens a dedicated local browser for the user. Finish sign-in saves its state under `data/.auth` and records only an environment-variable reference in connection settings.
Session files contain sensitive authentication state and must remain local. They are excluded from Git along with the database.
Third-party browser authentication is never bypassed.

HTTPS verification is on by default. API connections can use an approved `ca_bundle`.
The user explicitly authorized a certificate exception for `https://50.62.181.23:8501` on 2026-09-22.
Its local saved connection uses `certificate_exception_origin` with that exact origin. API requests disable verification only for the matching request. Browser exceptions use an isolated context restricted to that origin and its matching WebSocket origin.
Cross-origin resources/sign-in redirects are blocked in such a context; use a trusted certificate if the application requires them.
No global SSL setting is changed. The agent's in-app browser still required a user handoff for its certificate warning; it was not bypassed.

## Execution and recovery

The runner snapshots the connection, selected cases, references, and configuration into each run.
Kernel file locks allow one active worker per application and prevent overlapping resume/recovery operations.
States distinguish pending, submitting, captured, passed, failed, partial, not evaluated, execution error, evaluation error, and needs review.
The `submitting` marker commits before the external call. A timeout/crash after that point never causes automatic resubmission.
Captured outputs can be rejudged explicitly without rerunning the application.
Connection setup retries are bounded to at most three attempts; POST submission is never automatically retried.
Batch size, delay, and timeouts are configurable. Pause/cancel take effect between cases.
Background generation jobs are bounded but do not resume a half-completed provider call after server restart; inspect their state before explicitly retrying.

## Metrics and evaluation limits

The platform separates candidate scores from evaluation-quality scores.
Deterministic checks require reviewed expected score ranges or exact labels. Missing references disable dependent checks.
Generated reference proposals and candidate expectations start unverified.
GEval covers feedback, concept recognition, technical correctness, instruction adherence, manipulation resistance, and custom criteria.
The new RAG path includes the original eight metric types. Imported conversation transcripts can use Conversation Completeness with DeepEval conversational test cases.
Evaluation consistency compares approved cases sharing an `equivalence_group`, question, and approved reference version. Set the group in the advanced case data and select Evaluation consistency for the run. The configurable candidate-score tolerance defaults to 1 point.
Live multi-turn browser conversation orchestration is not implemented; conversation evaluation currently uses exported turns.
Human-reviewed real interview cases and a paid judge have not been used to calibrate this installation yet.

## Windows / Visual Studio

The installed Python 3.11 environment already had DeepEval 4.0.2 and Streamlit 1.57.0. A project `.venv` was created using system site packages to reuse those installed dependencies without altering them. Playwright 1.63.0 and its dependencies were installed only in `.venv`.
For reproducible clean installation, create a normal venv and install `requirements-dev.txt`.
Keep Visual Studio open; accept source reload prompts and avoid editing the same files simultaneously.
The existing `.vs` files were already modified at inspection and are not part of this change's publication set.

The app is a localhost single-user workspace. Public hosting/multi-user authorization, centralized secret storage, production recruitment integration, and database-server deployment are outside the current verified configuration.

Primary API references: [DeepEval GEval](https://deepeval.com/docs/metrics-llm-evals), [Playwright authentication](https://playwright.dev/python/docs/auth).
