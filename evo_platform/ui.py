"""Pages mounted inside EVO.py, retaining its navigation and visual identity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import streamlit as st
from .connectors import make_connector
from .evaluation import CATEGORIES, CRITERIA, RAG_METRICS, generate_cases, propose_reference
from .store import Store, encode, parse_records

PAGES = ['AI Dashboard', 'AI Application Testing', 'Web Application Connections', 'Reference & Chunk Management', 'AI Datasets', 'AI Test Execution', 'AI Evaluation Results']
ROOT = Path(__file__).resolve().parents[1]


def selected_application(store):
    apps = store.rows('SELECT * FROM applications ORDER BY name')
    if not apps:
        st.info('Create a connection in Web Application Connections. Choose import for offline input/output evaluation.')
        return None
    index = st.selectbox('Application', range(len(apps)), format_func=lambda i: apps[i]['name'])
    return apps[index]


def launch_worker(store, run_id):
    env = os.environ.copy()
    if st.session_state.get('openai_key'):
        env['OPENAI_API_KEY'] = st.session_state.openai_key
    env['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
    worker = subprocess.Popen([sys.executable, '-m', 'evo_platform.runner', '--db', store.path, '--run', run_id], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    st.session_state.setdefault('evo_workers', {})[run_id] = worker


def render(page):
    store = Store()
    st.title(page)
    try:
        if page == 'Web Application Connections':
            connections(store)
        elif page == 'AI Dashboard':
            dashboard(store)
        elif page == 'Reference & Chunk Management':
            chunks(store)
        elif page == 'AI Test Execution':
            execution(store)
        elif page == 'AI Evaluation Results':
            results(store)
        else:
            app = selected_application(store)
            if app:
                (discovery if page == 'AI Application Testing' else datasets)(store, app)
    except Exception as exc:
        st.error(f'{type(exc).__name__}: operation failed. Check the required fields, connection diagnostics, and configuration. No credentials are shown here.')


def connections(store):
    st.caption('1. Save connection settings. 2. Test access and selectors. 3. Import or synchronize a catalog. Credentials stay in environment variables.')
    saved = store.rows('SELECT * FROM applications ORDER BY name')
    selection = st.selectbox('Edit connection', ['New connection'] + [a['name'] for a in saved])
    existing = next((a for a in saved if a['name'] == selection), None)
    name = st.text_input('Application name', value=existing['name'] if existing else 'AI Interview Tool')
    kinds = ['import', 'api', 'browser', 'interview']
    kind = st.selectbox('Connector type', kinds, index=kinds.index(existing['kind']) if existing else 0)
    default = {'url': 'https://50.62.181.23:8501/interview', 'timeout': 60, 'headless': True, 'browser_channel': 'msedge' if os.name == 'nt' else ''}
    raw = st.text_area('Connection settings (JSON)', value=json.dumps(json.loads(existing['config']) if existing else default, indent=2), height=220)
    st.caption('Browser: input, submit, response, completion, reset, question, technology_select, question_select. API: catalog_path, submit_path, token_env, response_fields. Authentication: storage_state_env or login selectors with username_env/password_env. No raw secrets.')
    exception = st.checkbox('Use the explicitly approved certificate exception for https://50.62.181.23:8501 only', value=bool(existing and json.loads(existing['config']).get('certificate_exception_origin')))
    st.caption('This exception was authorized for your interview test server. Browser requests to other origins are blocked in that context. A trusted certificate remains the preferred setup.')
    if st.button('Save connection'):
        config = json.loads(raw)
        if exception:
            config['certificate_exception_origin'] = 'https://50.62.181.23:8501'
        else:
            config.pop('certificate_exception_origin', None)
        store.save_application(name, kind, config)
        st.success('Connection saved. No test answers submitted.')
    if existing and st.button('Test connection and selectors (no submission)'):
        connector = make_connector(existing['kind'], json.loads(existing['config']))
        try:
            connector.connect()
            st.json(connector.discover_capabilities())
            if hasattr(connector, 'diagnostics'):
                st.json(connector.diagnostics())
        finally:
            connector.close()


def discovery(store, app):
    st.caption('Import an authorized export, or synchronize a configured catalog. Random observations alone never establish complete coverage.')
    upload = st.file_uploader('Question catalog JSON or CSV', type=['json', 'csv'])
    st.code('[{"technology":"Your technology","question_id":"external-id","question":"Question text","concepts":["Concept"],"expected_answer":"Reference answer"}]', language='json')
    if upload and st.button('Import catalog'):
        records = parse_records(upload.getvalue().decode('utf-8-sig'), upload.name)
        st.json(store.import_catalog(app['id'], records, 'authorized import'))
    if app['kind'] != 'import' and st.button('Synchronize configured catalog'):
        connector = make_connector(app['kind'], json.loads(app['config']))
        try:
            connector.connect()
            records, totals = connector.catalog()
            st.json(store.import_catalog(app['id'], records, app['kind'], totals))
        finally:
            connector.close()
    if app['kind'] != 'import' and st.button('Discover available technologies'):
        connector = make_connector(app['kind'], json.loads(app['config']))
        try:
            connector.connect()
            technologies = connector.technologies()
            store.import_technologies(app['id'], technologies)
            st.dataframe(technologies)
        finally:
            connector.close()
    questions = store.questions(app['id'])
    technologies = [t['name'] for t in store.rows('SELECT name FROM technologies WHERE application_id=? ORDER BY name', (app['id'],))]
    all_technologies = st.checkbox('Select All Technologies', value=True)
    selected = st.multiselect('Technologies', technologies, default=technologies if all_technologies else [])
    st.dataframe([q for q in questions if q['technology'] in selected], use_container_width=True)
    latest = store.rows('SELECT * FROM discoveries WHERE application_id=? ORDER BY rowid DESC LIMIT 1', (app['id'],))
    if latest:
        st.json(json.loads(latest[0]['statistics']))
    st.info('Reference information from imports starts unverified. Review and approve it in Reference & Chunk Management.')


def chunks(store):
    kind = st.selectbox('Chunk type', ['structured', 'document'])
    rows = store.rows('SELECT c.*,q.text question FROM chunks c LEFT JOIN questions q ON c.question_id=q.id WHERE kind=? ORDER BY c.created_at DESC,c.version DESC', (kind,))
    st.dataframe(rows, use_container_width=True)
    if not rows:
        st.info('Structured chunks are created on catalog import. Successful document uploads are mirrored here without changing Supabase.')
        return
    index = st.selectbox('Chunk to review', range(len(rows)), format_func=lambda i: f"{rows[i]['question'] or rows[i]['document_id']} · v{rows[i]['version']} · {rows[i]['validation']}")
    row = rows[index]
    content = st.text_area('Reference content', json.dumps(json.loads(row['content']), indent=2), height=300)
    approved = st.checkbox('I reviewed this content and approve it for evaluation')
    if st.button('Save new version'):
        store.revise_chunk(row['id'], json.loads(content), 'approved' if approved else 'unverified')
        st.success('New version saved. Previous versions and existing dataset references remain intact.')
    if st.button('Deactivate this version'):
        store.execute('UPDATE chunks SET active=0 WHERE id=?', (row['id'],))
        st.success('Version deactivated; historical results are preserved.')
    if kind == 'structured' and st.button('Generate independent reference proposal (unverified)'):
        proposal = propose_reference(row['question'], st.session_state.openai_model, st.session_state.openai_key)
        store.revise_chunk(row['id'], proposal, 'generated')
        st.success('Generated a new unverified version. Review and approve it before using it as evaluation ground truth. Historical approved versions remain saved.')
    imported = st.file_uploader('Import replacement content for the selected chunk', type=['json'])
    if imported and st.button('Import as a new unverified version'):
        content = json.loads(imported.getvalue())
        if not isinstance(content, dict):
            raise ValueError('Chunk content must be a JSON object')
        store.revise_chunk(row['id'], content)
        st.success('Imported a new version for review.')
    st.download_button('Export chunks', encode(rows), 'chunks.json', 'application/json')


def datasets(store, app):
    questions = store.questions(app['id'])
    if not questions:
        st.info('Import or synchronize a question catalog first.')
        return
    st.caption('Datasets pin the reference version at creation. Generated cases and imported expectations remain unverified until you approve them.')
    name = st.text_input('Dataset name', 'Interview regression')
    techs = sorted({q['technology'] for q in questions})
    technologies = st.multiselect('Technologies', techs, default=techs)
    pool = [q for q in questions if q['technology'] in technologies]
    selected = st.multiselect('Questions', [q['id'] for q in pool], default=[q['id'] for q in pool], format_func=lambda qid: next(q['text'] for q in pool if q['id'] == qid))
    categories = st.multiselect('Answer categories', CATEGORIES, default=['Fully correct', 'Partially correct', 'Empty'])
    count = st.number_input('Cases per category', min_value=1, max_value=20, value=1)
    if st.button('Generate candidate answers using configured OpenAI model'):
        cases = []
        for question in pool:
            if question['id'] in selected:
                cases.extend(generate_cases(question, store.reference(question['id']), categories, count, st.session_state.openai_model, st.session_state.openai_key))
        if not cases:
            raise ValueError('Select questions')
        store.create_dataset(app['id'], name, cases, 'generated-unverified')
        st.success('Generated dataset saved for review.')
    upload = st.file_uploader('Import test cases / exported input-output records', type=['json', 'csv'])
    st.caption('Each record requires question_id (local UUID from the catalog table) and candidate_input. Optional: actual {output, score, concepts}, expected_output, score_range [min,max], expected_concepts. Imports never self-approve.')
    if upload and st.button('Import dataset'):
        store.create_dataset(app['id'], name, parse_records(upload.getvalue().decode('utf-8-sig'), upload.name))
        st.success('Dataset imported.')
    sets = store.rows('SELECT * FROM datasets WHERE application_id=? ORDER BY rowid DESC', (app['id'],))
    if not sets:
        return
    dataset_id = st.selectbox('Saved dataset', [d['id'] for d in sets], format_func=lambda did: next(d['name'] for d in sets if d['id'] == did))
    cases = store.rows('SELECT * FROM cases WHERE dataset_id=?', (dataset_id,))
    st.dataframe(cases)
    if cases:
        case_id = st.selectbox('Review case', [c['id'] for c in cases])
        case = next(c for c in cases if c['id'] == case_id)
        body = st.text_area('Test case', json.dumps(json.loads(case['content']), indent=2), height=200)
        approve = st.checkbox('Approve this answer and expected result')
        if st.button('Save reviewed case'):
            parsed = json.loads(body)
            if parsed.get('question_id') != case['question_id'] or not isinstance(parsed.get('candidate_input'), str):
                raise ValueError('Question identity cannot change; candidate input must be text')
            store.execute('UPDATE cases SET content=?,validation=? WHERE id=?', (encode(parsed), 'approved' if approve else 'unverified', case_id))
            st.success('Case saved. Existing run snapshots are unchanged.')
        st.download_button('Export dataset', encode([json.loads(c['content']) for c in cases]), 'dataset.json', 'application/json')


def execution(store):
    app = selected_application(store)
    if not app:
        return
    sets = store.rows('SELECT * FROM datasets WHERE application_id=?', (app['id'],))
    if sets:
        dataset_id = st.selectbox('Dataset', [d['id'] for d in sets], format_func=lambda did: next(d['name'] for d in sets if d['id'] == did))
        cases = store.rows('SELECT c.*,t.name technology,q.text question FROM cases c JOIN questions q ON c.question_id=q.id JOIN technologies t ON q.technology_id=t.id WHERE dataset_id=?', (dataset_id,))
        technologies = sorted({c['technology'] for c in cases})
        selected_tech = st.multiselect('Selected technologies', technologies, default=technologies)
        eligible = [c for c in cases if c['technology'] in selected_tech]
        case_ids = st.multiselect('Selected test cases', [c['id'] for c in eligible], default=[c['id'] for c in eligible], format_func=lambda cid: next(c['question'] + ' · ' + c['validation'] for c in eligible if c['id'] == cid))
        names = ['Score accuracy', 'Exact concept labels', 'JSON output'] + list(CRITERIA) + list(RAG_METRICS)
        metrics = st.multiselect('Metrics', names, default=['Score accuracy'])
        st.caption('Score accuracy / exact concepts require approved case expectations. Reference-based GEval metrics require an approved reference. Unavailable checks are recorded explicitly, never counted as passing.')
        st.dataframe([{'metric': name, 'required fields': ('actual output, ' + ', '.join(RAG_METRICS[name][1]) if name in RAG_METRICS else CRITERIA.get(name, ('approved expectations or output schema', ''))[0] or 'input and actual output')} for name in metrics])
        threshold = st.slider('DeepEval quality threshold (0–1)', 0., 1., .5)
        batch_size = st.number_input('Cases per batch before pausing', 1, 10000, 25)
        interval = st.number_input('Seconds between cases', 0., 60., 1.)
        custom = st.text_area('Custom criteria (when selected)')
        st.caption('One worker executes each run sequentially. Pausing and cancellation take effect between cases; an in-flight submission finishes capture first.')
        if st.button('Create and start run', disabled=not (case_ids and metrics)):
            run_id = store.create_run(app['id'], case_ids, {'metrics': metrics, 'threshold': threshold, 'batch_size': batch_size, 'interval': interval, 'judge_model': st.session_state.openai_model, 'custom_criteria': custom, 'technologies': selected_tech})
            launch_worker(store, run_id)
            st.success('Run started: ' + run_id)
    runs = store.rows('SELECT * FROM runs WHERE application_id=? ORDER BY rowid DESC', (app['id'],))
    if not runs:
        return
    run_id = st.selectbox('Run', [r['id'] for r in runs])
    show_progress(store, run_id)
    a, b, c = st.columns(3)
    if a.button('Pause'):
        store.execute("UPDATE runs SET status='paused' WHERE id=? AND status='running'", (run_id,))
    if b.button('Resume'):
        worker = st.session_state.get('evo_workers', {}).get(run_id)
        if worker and worker.poll() is None:
            st.info('Wait for the current case to finish before resuming.')
        else:
            launch_worker(store, run_id)
    if c.button('Cancel'):
        store.execute("UPDATE runs SET status='cancelled' WHERE id=? AND status IN ('pending','running','paused','interrupted')", (run_id,))
    stopped = st.checkbox('I verified the previous worker has exited (interrupted run recovery)')
    if st.button('Recover interrupted run', disabled=not stopped):
        from .runner import recover
        worker = st.session_state.get('evo_workers', {}).get(run_id)
        if worker and worker.poll() is None:
            st.error('The worker is still active.')
        else:
            recover(store, run_id)
            st.success('Recovered. Ambiguous submissions need manual reconciliation and will not be resubmitted.')


@st.fragment(run_every=3)
def show_progress(store, run_id):
    rows = store.results(run_id)
    finished = sum(row['state'] not in ('pending', 'submitting', 'captured') for row in rows)
    st.progress(finished / len(rows) if rows else 0, text=f'{finished}/{len(rows)} cases finished')
    st.dataframe([{'case': r['case_id'], 'state': r['state'], 'error': r['error']} for r in rows])


def results(store):
    runs = store.rows('SELECT r.*,a.name application FROM runs r JOIN applications a ON a.id=r.application_id ORDER BY r.rowid DESC')
    if not runs:
        st.info('No runs yet.')
        return
    run_id = st.selectbox('Run', [r['id'] for r in runs], format_func=lambda rid: next(r['application'] + ' · ' + r['created_at'] + ' · ' + r['status'] for r in runs if r['id'] == rid))
    rows = store.results(run_id)
    technologies = sorted({json.loads(r['snapshot'])['technology'] for r in rows})
    selected = st.multiselect('Technology filter', technologies, default=technologies)
    states = sorted({r['state'] for r in rows})
    statuses = st.multiselect('Status filter', states, default=states)
    visible = [r for r in rows if json.loads(r['snapshot'])['technology'] in selected and r['state'] in statuses]
    st.dataframe([{'id': r['id'], 'question': json.loads(r['snapshot'])['question'], 'technology': json.loads(r['snapshot'])['technology'], 'state': r['state'], 'candidate_score': json.loads(r['actual'] or '{}').get('score'), 'quality_metrics': r['metrics'], 'timestamp': r['updated_at']} for r in visible])
    if visible:
        chosen = st.selectbox('Result details', [r['id'] for r in visible])
        row = next(r for r in visible if r['id'] == chosen)
        for field in ('snapshot', 'actual', 'metrics'):
            st.subheader({'snapshot': 'Input, reference and expected evaluation', 'actual': 'Actual application evaluation (candidate score)', 'metrics': 'Evaluation quality (0–1)'}[field])
            st.json(json.loads(row[field] or '{}'))
    for format in ('csv', 'json'):
        st.download_button('Export ' + format.upper(), store.export_results(run_id, format), f'{run_id}.{format}')


def dashboard(store):
    a, b, c = st.columns(3)
    a.metric('Technologies', store.rows('SELECT COUNT(*) n FROM technologies')[0]['n'])
    b.metric('Questions', store.rows('SELECT COUNT(*) n FROM questions')[0]['n'])
    c.metric('Evaluation failures', store.rows("SELECT COUNT(*) n FROM results WHERE state='failed'")[0]['n'])
    st.dataframe(store.rows('SELECT state,COUNT(*) count FROM results GROUP BY state'))
    st.dataframe(store.rows('SELECT t.name technology,COUNT(DISTINCT q.id) questions,COUNT(DISTINCT c.question_id) questions_with_cases FROM technologies t LEFT JOIN questions q ON q.technology_id=t.id LEFT JOIN cases c ON c.question_id=q.id GROUP BY t.id'))
    st.dataframe(store.rows('SELECT r.id,a.name application,r.status,r.created_at FROM runs r JOIN applications a ON a.id=r.application_id ORDER BY r.rowid DESC'))
