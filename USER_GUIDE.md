# Using E.V.O

For automated AI Interview testing and Confident AI uploads, start with [INTERVIEW_AUTOMATION.md](INTERVIEW_AUTOMATION.md). The earlier website-mapping instructions below apply to generic browser connections.

## Open the app

In PowerShell, open your existing project folder and run:

```powershell
cd C:\Users\Admin\source\repos\DeepEval-RAG-Evaluator
.\Start-EVO.ps1
```

Then open **http://127.0.0.1:8080**. Keep the server terminal running. Visual Studio can stay open.

## Connect an application — the simple way

Go to **Applications → Add application**.

| Choose | What you enter | Use it when |
|---|---|---|
| Website | Application name and website address | You normally use the AI through its website |
| API | Application name, endpoint, and optional access token | The application provides an authorized API |
| Import results | Application name | You already have exported questions, answers, and AI output |

Advanced options are collapsed. You do not need to fill them in just to save a connection.

### Website

1. Enter the name and URL, then **Save connection**.
2. If login is required, click **Sign in**. Use your dedicated test account in the browser window.
3. Return to E.V.O and click **Finish sign-in**. The local session can be reused.
4. Click **Check connection**. E.V.O opens the website and suggests controls it can identify reliably.
5. Confirm the answer box, submit button, reply area, and completion indicator before live testing.

Some websites need a one-time custom mapping because they have unusual interview flows, audio-only input, or nonstandard controls. The app does not guess where to submit answers or pretend it collected every question. If discovery is not configured yet, **Import catalog** lets you continue immediately.

**AI Interview Tool:** its saved address is `https://50.62.181.23:8501/interview`.
The approved certificate exception is saved only for that origin. Site-specific controls are still unverified; start with **Check connection**, not a full test batch.
If a browser cannot start, launch E.V.O from a normal local PowerShell session. The development sandbox blocked Playwright subprocess pipes with `WinError 5`.

### API

Paste the submission endpoint. The optional access token stays in server memory; it is not written into the saved connection.
The standard connector sends question ID, question, technology, and candidate answer, and reads output/score/feedback fields.
If your API uses different fields or several workflow steps, configure its mapping once using the technical guide.
Checking an API connection validates client configuration; an actual catalog request or a small submission is still needed to verify the server contract.

### Import results

This is the quickest path for testing the platform without website access, login, or paid calls.

1. Add an application using **Import results**.
2. Choose **Import catalog** and import question records.
3. The catalog table shows each question's local ID. Use that ID in imported test cases.
4. Import cases in **Datasets** with the candidate input and actual application output.
5. Review any expected scores before using the **Score accuracy** metric.

## Add questions and references

Under **Applications**, use an authorized question export or a configured catalog synchronization.
The catalog preserves technologies, IDs, difficulty, duplicate observations, and coverage status.

Go to **Reference library** and click **Review** beside a question.
Edit the expected answer and concepts, then check the approval box and save a new version.
If you ask E.V.O to generate a proposal, it remains unverified until you review it.
Previous versions and historical test results remain intact.

## Create test answers

In **Datasets**, choose the application, then either:

- **Import dataset:** reuse existing test answers and expected results.
- **Generate test cases:** choose questions, answer categories, and count per category. This requires approved references and an OpenAI key in Settings.

Review generated cases before approving expectations. Set an expected score range only when you have a reviewed basis for it. Generated scores are never treated as official marking criteria.

## Run an evaluation

1. Open **Test runs → New test run**.
2. Select the application, dataset, and cases.
3. Choose the metrics that match the available information.
4. Start with one or two cases. Confirm the captured question and feedback before increasing the batch.
5. Watch the progress indicator. Pause, resume, or cancel between cases.

Numeric score checks, exact concept labels, and JSON validation do not need an LLM judge.
GEval and other model-based metrics use the configured model and may incur provider charges.
Checks lacking required information appear as unavailable. A partly evaluated case is not presented as a fully passing case.

## Understand the results

Open **Results**, select a run, filter it, and click **Inspect**.

- **Candidate score** is the score assigned by the application, such as 8/10.
- **Quality score** evaluates how well the AI application behaved, usually on a 0–1 scale.
- **Evaluation failure** means a completed check did not meet its criterion.
- **Execution error** means the connection or capture failed.
- **Needs review** means a submission may have reached the application, so E.V.O will not submit it again automatically.

Inspect each metric's reason and direction; bias, toxicity, and hallucination raw scores use lower-is-better semantics. The overview aggregate normalizes direction.
Export JSON or CSV for analysis, or PDF and Word reports for sharing.

## Run document-based RAG testing

1. Configure your OpenAI model and RAG endpoint in **Settings**. Supabase is optional for the new local workflow.
2. Open **RAG testing** and upload a PDF, DOCX, TXT, CSV, or XLSX document.
3. Set chunk size and overlap. Enable Supabase upload if needed.
4. Generate goldens from a stored document.
5. Review questions and expected answers, saving a new version.
6. Evaluate the dataset against the configured RAG endpoint.

Contextual metrics need actual `retrieval_context` from the endpoint. When it is missing, those checks are unavailable; the source document is not falsely represented as the system's actual retrieval.
The new interface exports PDF and Word reports as well as JSON. The original CLI and legacy UI remain available for existing Confident AI cloud operations.

## If something fails

- **No questions yet:** import a catalog or finish connection mapping; saving a URL alone does not establish a question catalog.
- **Reference unavailable:** approve the relevant reference and create a dataset pinned to that version.
- **API key missing:** enter it in Settings or configure `OPENAI_API_KEY` before launching.
- **Browser access denied:** run the application in a normal local terminal with Edge/Playwright available.
- **Login expired:** use Sign in again and save the refreshed session.
- **Interrupted worker:** use Recover only after its prior process has exited. Held submissions remain held.
- **Judge error after successful capture:** retry judge errors only; this reuses captured output without resubmitting the candidate answer.

Your data is local. Back up the `data` directory while the server is stopped. Do not add browser sessions, credentials, or the database to GitHub.


