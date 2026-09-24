# E.V.O — Universal AI Testing

E.V.O evaluates RAG pipelines and other AI applications from one local web workspace.
The primary interface uses HTML, CSS, and JavaScript served by FastAPI. It does not run Streamlit.
The existing Python RAG modules and legacy interface remain available for compatibility.

## Start on Windows

From this repository in PowerShell:

```powershell
.\Start-EVO.ps1
```

Open **http://127.0.0.1:8080**. Visual Studio can remain open.

First-time installation:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Windows website connections use installed Microsoft Edge (`browser_channel: msedge`).
For Chromium instead, run `.\.venv\Scripts\python.exe -m playwright install chromium`
and clear the browser channel in the connection's advanced options.

## Start using it

1. **Applications → Add application:** choose Website, API, or Import results.
2. For a website, enter its name and URL, save, sign in if needed, then **Check connection**.
3. Import or synchronize the question catalog.
4. **Reference library:** review expected answers and concepts, then approve them.
5. **Datasets:** import test answers or generate them from approved references.
6. **Test runs:** choose a dataset and metrics, start a small run, then inspect **Results**.

For document-based testing, use **RAG testing** to upload, chunk, generate goldens, review, and evaluate.

See [USER_GUIDE.md](USER_GUIDE.md) for the simple walkthrough,
[UNIVERSAL_TESTING.md](UNIVERSAL_TESTING.md) for technical configuration,
and [VALIDATION.md](VALIDATION.md) for actual test results and outstanding access requirements.

## Current readiness

The local web workspace, SQL storage, imported-data evaluations, API contract, and background workers have automated coverage.
Live integration with the AI Interview Tool is **not yet verified**. Its website controls and authorized question catalog still need inspection/access.
The saved local interview connection includes the certificate exception explicitly approved for `https://50.62.181.23:8501`; HTTPS verification is not disabled globally.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -m "not browser" -q
# Full suite where browser subprocesses are permitted:
.\.venv\Scripts\python.exe -m pytest -q
```

The browser connector test is a real Playwright test against a synthetic local website.
It does not prove the external interview website works.

## Storage and credentials

Local SQLite data lives in `data/evo.sqlite3` by default. `EVO_DB_PATH` can change this location.
Migrations run automatically without dropping existing user data. Supabase remains available for the existing RAG workflow.
The application binds to the local machine only; it is not configured as a public multi-user service.
Keep credentials in environment variables or the Settings session. Local database, browser sessions, and virtual environments are excluded from Git.

Original setup and legacy Streamlit usage are retained in [docs/LEGACY_RAG.md](docs/LEGACY_RAG.md).
