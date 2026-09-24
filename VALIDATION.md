Latest update: required name/surname web sign-in, user initials, activity attribution, unwanted-dataset removal and cancelled-run clearing. Full suite: 66 passed, 1 browser test excluded. JavaScript syntax check passed. Restart local E.V.O to activate. See USERS_AND_CLEANUP.md.

Universal metric update: all eight original native DeepEval metrics now execute for non-RAG inputs too. Native/GEval defaults apply to every connector; result metadata names the implementation. The suite passed 62 tests, with one browser test excluded. See UNIVERSAL_METRICS.md.

# Latest interview API update

See INTERVIEW_AUTOMATION.md for the current automation and cloud status. The browser integration notes below describe the earlier browser-only path; the new practice API path has verified configuration/question discovery. Live submission and cloud upload remain unverified until keys are supplied.

# Validation and readiness

Status: ready for **local platform testing**. The actual AI Interview Tool integration is not yet verified.

## Completed checks

- Original Streamlit application startup succeeded after a slow initial import. All original navigation pages and compatibility extensions passed AppTest smoke checks.
- New FastAPI service started on localhost:8080 without using Streamlit for its interface.
- New web dashboard, application list, and simplified connection form were opened in the in-app browser. Dashboard and connection layout were visually inspected.
- JavaScript syntax check passed with Node 24.19.0.
- Source diff whitespace check passed with Windows CRLF handling enabled.
- Automated suite: **62 passed**, with the separately marked browser test excluded because of the documented sandbox restriction.

Covered behavior includes migrations preserving data, SQL foreign keys/transactions, document chunk persistence, versioned references, per-technology question identity/deduplication, authoritative completeness checks, dataset review and immutable run snapshots, score separation, unavailable metrics, real GEval orchestration with a scripted offline judge, API catalog pagination, local API submission, missing authentication, scoped TLS configuration, ambiguous-submission recovery, pause/resume, worker locks, random-question rematching, real background worker execution, web API workflows, local RAG upload, settings secret redaction, cross-origin protection, and report formats.

The scripted judge tests execute DeepEval code but do not validate a paid model's semantic accuracy.
Generated-reference/candidate tests validate orchestration and review gates; no paid generation was performed.

## Browser test blocker

Playwright 1.63.0 was installed in the project virtual environment.
The real Playwright connector test against a synthetic local website failed before browser launch because the sandbox denied Windows subprocess pipe creation:

`PermissionError: [WinError 5] Access is denied`

This is not reported as a passing or skipped-after-success test. Run the full suite from a normal local PowerShell session:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The CI workflow installs Chromium and runs the complete suite on Linux if the changes are pushed.
CI has not run from this workspace yet.

## Actual interview site

Opening `https://50.62.181.23:8501/interview` in the agent browser returned `net::ERR_CERT_AUTHORITY_INVALID`.
The user authorized a narrowly scoped certificate exception. That exception is implemented and saved in the local interview connection; it is not global.
The browser security warning was not bypassed by the agent.

Still unverified: authentication, actual technology widgets, actual interview question flow, official core concepts/rubrics, question catalog totals, answer submission, streaming completion, captured scores/feedback, and end-to-end DeepEval evaluation of the real application.
No real candidate records were submitted, and no full interview batch was run.
Discovery remains unavailable until actual selectors or an authorized catalog endpoint/export are configured.

## Remaining product scope

- Complex website workflows and audio-only interviews need a dedicated inspected adapter.
- Multi-turn evaluation currently accepts exported conversation turns; live conversational browser orchestration is not implemented.
- Consistency comparison requires approved cases with an explicit equivalence group and the same approved reference version.
- The new SQL layer uses SQLite; additional SQL server backends are not implemented.
- Legacy Confident AI cloud operations remain in the retained CLI/legacy UI; they are not exposed in the new web interface.
- Model-judge calibration against approved real reference cases still requires the user's reference data and provider access.

## GitHub status

The repository was reachable at the user-provided GitHub URL using Git's OpenSSL TLS backend with verification enabled.
The default Windows schannel backend reported `SEC_E_NO_CREDENTIALS`.
Creating a branch in the existing repository failed because `.git/refs/heads/...lock` could not be written, even after repository permissions were requested.
No commit or GitHub push was made by the agent. The current user branch and existing Visual Studio state were preserved.

Run `Publish-EVO.ps1` from a normal local PowerShell session to create a separate branch, stage only the explicit project files, commit, and push. It refuses pre-existing staged changes and never force-pushes.

## Safe first test

Use an Import results application with synthetic records and deterministic metrics first.
Then test one or two live cases using a dedicated test account after connection controls and reference matching are verified.





## User management and bulk review update — 2026-09-24

`pytest -m 'not browser' -q`: 75 passed, 1 browser test deselected. JavaScript syntax check passed using Node. Tests cover normalized identity reuse, user editing/removal/restoration and session revocation, completed-run and application removal with retained snapshots, bulk reference/case proposal and approval, partial failures and concurrent human edits. Proposal providers were mocked; this update did not make paid provider calls or upload real data to Confident AI. Live browser interaction was not verified. Restart the local server to activate the updated routes and migration.

## Document/process cleanup and Overview filtering
Non-browser suite: 78 passed, 1 browser test deselected. JavaScript syntax and whitespace checks passed. Tests verify document removal/re-upload, busy-document protection, persistent dismissal of terminal jobs, and exclusion of all removed-application contributions from Overview while preserving historical results. Live browser interaction was not tested for this update.

