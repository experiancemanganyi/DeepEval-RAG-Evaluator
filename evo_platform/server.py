"""Local FastAPI service for the E.V.O web interface. No Streamlit dependency."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .connectors import make_connector, ConnectorError
from .evaluation import CATEGORIES, CRITERIA, RAG_METRICS, NATIVE_METRICS, LOCAL_CHECKS, metric_implementation, all_deepeval_metrics, generate_cases, propose_reference, evaluate_output
from .store import Store, encode, uid, parse_records
from .runner import recover, worker_lock
from .identity import COOKIE, current_user, session_user, sign_in, log_activity
from .identity import clean_identity

ROOT = Path(__file__).resolve().parents[1]


def create_app(database_path=None):
    app = FastAPI(title='E.V.O Universal AI Testing', docs_url='/api/docs', redoc_url=None)
    store = Store(database_path)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='evo-job')
    workers = {}
    login_sessions = {}
    settings = {key: os.getenv(env, '') for key, env in {'openai_key': 'OPENAI_API_KEY', 'judge_model': 'OPENAI_MODEL', 'supabase_url': 'SUPABASE_URL', 'supabase_key': 'SUPABASE_KEY', 'supabase_table': 'SUPABASE_TABLE', 'webhook_url': 'RAG_WEBHOOK'}.items()}
    settings['judge_model'] = settings['judge_model'] or 'gpt-4o-mini'
    settings['supabase_table'] = settings['supabase_table'] or 'eval_documents'
    settings['confident_key'] = os.getenv('CONFIDENT_API_KEY') or os.getenv('CONFIDENT_AI_API_KEY', '')
    app.state.store, app.state.settings = store, settings
    for saved in store.rows('SELECT id,config FROM applications'):
        env_name = 'EVO_BROWSER_STATE_' + saved['id'].replace('-', '_')
        state_file = Path(store.path).parent / '.auth' / (saved['id'] + '.json')
        if json.loads(saved['config']).get('storage_state_env') == env_name and state_file.exists():
            os.environ[env_name] = str(state_file)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return JSONResponse({'detail': 'Cross-origin mutations are blocked'}, status_code=403)
        user = session_user(store, request.cookies.get(COOKIE))
        public = request.url.path in ('/api/health', '/api/session', '/api/login')
        if request.url.path.startswith('/api/') and not public and not user:
            return JSONResponse({'detail': 'Sign in with your name and surname first'}, status_code=401)
        marker = current_user.set(user)
        try:
            response = await call_next(request)
            if user and request.method not in ('GET', 'HEAD', 'OPTIONS'):
                log_activity(store, user, request.method, request.url.path, response.status_code)
        finally:
            current_user.reset(marker)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.exception_handler(ConnectorError)
    async def connector_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse({'detail': type(exc).__name__ + ': check configuration or service availability. Credentials are not included in diagnostics.'}, status_code=500)

    def one(sql, params=()):
        rows = store.rows(sql, params)
        if not rows:
            raise HTTPException(404, 'Record not found')
        return rows[0]

    def application(app_id):
        row = one('SELECT * FROM applications WHERE id=? AND deleted_at IS NULL', (app_id,))
        row['config'] = json.loads(row['config'])
        return row

    def start_worker(run_id):
        run_config = json.loads(store.rows('SELECT config FROM runs WHERE id=?', (run_id,))[0]['config'])
        if any(m not in ('Score accuracy', 'Exact concept labels', 'JSON output', 'Evaluation consistency') for m in run_config.get('metrics', [])) and not settings['openai_key']:
            raise ValueError('Save your OpenAI key in Settings before running model-based checks. The pending run can be resumed afterward.')
        active = workers.get(run_id)
        if active and active.poll() is None:
            raise HTTPException(409, 'This worker is still finishing its current case')
        env = os.environ.copy()
        if settings['openai_key']:
            env['OPENAI_API_KEY'] = settings['openai_key']
        env['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
        env['CONFIDENT_OPEN_BROWSER'] = 'false'
        if settings['confident_key']:
            env['CONFIDENT_API_KEY'] = settings['confident_key']
        workers[run_id] = subprocess.Popen([sys.executable, '-m', 'evo_platform.runner', '--db', store.path, '--run', run_id], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def job(kind, action, document_id=None):
        job_id = uid()
        actor = current_user.get()
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if document_id and not db.execute("SELECT 1 FROM chunks WHERE document_id=? AND kind='document' AND active=1", (document_id,)).fetchone():
                raise ValueError('This document has been removed; upload it again before generation')
            db.execute('INSERT INTO jobs(id,kind,initiated_by,document_id) VALUES(?,?,?,?)', (job_id, kind, actor['id'] if actor else None, document_id))
        def progress(fraction, message):
            store.execute('UPDATE jobs SET progress=?,message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (fraction, message, job_id))
        def work():
            marker = current_user.set(actor)
            store.execute("UPDATE jobs SET state='running' WHERE id=?", (job_id,))
            try:
                result = action(progress)
                store.execute("UPDATE jobs SET state='completed',progress=1,result=?,message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (encode(result), result.get('message', 'Completed') if isinstance(result, dict) else 'Completed', job_id))
            except Exception as exc:
                message = str(exc) if isinstance(exc, (ValueError, ConnectorError)) else type(exc).__name__ + ': check service configuration; no automatic retry'
                store.execute("UPDATE jobs SET state='failed',message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (message, job_id))
            finally:
                if actor:
                    state = store.rows('SELECT state FROM jobs WHERE id=?', (job_id,))[0]['state']
                    log_activity(store, actor, 'JOB_' + state.upper(), job_id)
                current_user.reset(marker)
        pool.submit(work)
        return {'job_id': job_id}

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'database': 'connected', 'interface': 'web'}

    @app.get('/api/session')
    def get_session():
        return {'user': current_user.get()}

    @app.post('/api/login')
    def login(body: dict):
        token, user = sign_in(store, body.get('name', ''), body.get('surname', ''))
        log_activity(store, user, 'SIGN_IN', 'workspace')
        response = JSONResponse({'user': user})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', max_age=12 * 3600)
        return response

    @app.post('/api/logout')
    def logout(request: Request):
        token = request.cookies.get(COOKIE, '')
        store.execute('DELETE FROM user_sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @app.get('/api/activity')
    def activity():
        return store.rows('SELECT actor,action,target,status,created_at FROM activity_log ORDER BY rowid DESC LIMIT 200')

    @app.get('/api/users')
    def users():
        return store.rows('SELECT id,name,surname,created_at,deleted_at FROM users ORDER BY surname,name')

    @app.delete('/api/users/{user_id}')
    def remove_user(user_id: str):
        if user_id == current_user.get()['id']:
            raise HTTPException(409, 'Sign in as another user before removing your own profile')
        one('SELECT id FROM users WHERE id=? AND deleted_at IS NULL', (user_id,))
        with store.connection() as db:
            db.execute('UPDATE users SET deleted_at=CURRENT_TIMESTAMP WHERE id=?', (user_id,))
            db.execute('DELETE FROM user_sessions WHERE user_id=?', (user_id,))
        store.record_change('REMOVE_USER', user_id)
        return {'ok': True}

    @app.post('/api/users/{user_id}/restore')
    def restore_user(user_id: str):
        one('SELECT id FROM users WHERE id=?', (user_id,))
        store.execute('UPDATE users SET deleted_at=NULL WHERE id=?', (user_id,))
        store.record_change('RESTORE_USER', user_id)
        return {'ok': True}

    @app.delete('/api/connections/{app_id}')
    def remove_application(app_id: str):
        application(app_id)
        with worker_lock(store, app_id) as acquired:
            if not acquired:
                raise HTTPException(409, 'Wait for the application worker to stop before removing it')
            if store.rows("SELECT id FROM runs WHERE application_id=? AND status IN ('pending','running','paused','interrupted') AND deleted_at IS NULL", (app_id,)):
                raise HTTPException(409, 'Finish or cancel pending and active runs before removing this application')
            store.execute('UPDATE applications SET deleted_at=CURRENT_TIMESTAMP WHERE id=?', (app_id,))
        return {'ok': True, 'message': 'Application removed. Historical results remain available.'}

    @app.post('/api/users')
    def add_user(body: dict):
        name, surname, key = clean_identity(body.get('name', ''), body.get('surname', ''))
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT id FROM users WHERE identity_key=?', (key,)).fetchone():
                raise HTTPException(409, 'A user with this name and surname already exists')
            user_id = uid()
            db.execute('INSERT INTO users(id,name,surname,identity_key) VALUES(?,?,?,?)', (user_id, name, surname, key))
        store.record_change('ADD_USER', user_id)
        return {'id': user_id}

    @app.put('/api/users/{user_id}')
    def edit_user(user_id: str, body: dict):
        name, surname, key = clean_identity(body.get('name', ''), body.get('surname', ''))
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
                raise HTTPException(404, 'User not found')
            if db.execute('SELECT id FROM users WHERE identity_key=? AND id!=?', (key, user_id)).fetchone():
                raise HTTPException(409, 'A user with this name and surname already exists')
            db.execute('UPDATE users SET name=?,surname=?,identity_key=? WHERE id=?', (name, surname, key, user_id))
        store.record_change('EDIT_USER', user_id)
        return {'ok': True}

    @app.post('/api/references/bulk-approve')
    def approve_selected(body: dict):
        if body.get('reviewed') is not True:
            raise ValueError('Confirm that you reviewed the selected content before approval')
        return {'ids': store.approve_references(body['application_id'], body.get('chunk_ids', []))}

    @app.post('/api/references/bulk-generate')
    def generate_selected(body: dict):
        app_id = body['application_id']
        ids = list(dict.fromkeys(body.get('chunk_ids', [])))
        if not ids or len(ids) > 200:
            raise ValueError('Select between 1 and 200 references')
        rows = []
        for chunk_id in ids:
            row = one('SELECT c.*,q.text question FROM chunks c JOIN questions q ON q.id=c.question_id JOIN technologies t ON t.id=q.technology_id WHERE c.id=? AND t.application_id=?', (chunk_id, app_id))
            latest = store.reference(row['question_id'])
            if not latest or latest['id'] != chunk_id or row['validation'] == 'approved':
                raise ValueError('Select the latest unapproved references; refresh the list if it changed')
            rows.append(row)
        if not settings['openai_key']:
            raise ValueError('Add your OpenAI key in Settings before generating proposals')
        def action(progress):
            generated, errors = [], []
            for index, row in enumerate(rows):
                progress(index / len(rows), f'Generating proposal {index + 1} of {len(rows)}')
                try:
                    content = propose_reference(row['question'], settings['judge_model'], settings['openai_key'])
                    new_id = store.revise_chunk(row['id'], content, 'generated', require_current=True)
                    store.record_change('GENERATE_REFERENCE', new_id)
                    generated.append(new_id)
                except Exception as exc:
                    errors.append({'question': row['question'], 'error': type(exc).__name__ + ': generation failed or reference changed; review and retry this question'})
            return {'generated': generated, 'errors': errors, 'message': f'{len(generated)} proposals saved; {len(errors)} failed. Refresh references, review the proposals, then approve selected.'}
        return job('Bulk reference proposals', action)

    @app.delete('/api/datasets/{dataset_id}')
    def delete_dataset(dataset_id: str):
        one('SELECT id FROM datasets WHERE id=? AND deleted_at IS NULL', (dataset_id,))
        active = store.rows("SELECT r.id FROM runs r JOIN results x ON x.run_id=r.id JOIN cases c ON c.id=x.case_id WHERE c.dataset_id=? AND (r.status='running' OR x.state='submitting') LIMIT 1", (dataset_id,))
        if active:
            raise HTTPException(409, 'Wait for the active run to finish before deleting this dataset')
        store.execute('UPDATE datasets SET deleted_at=CURRENT_TIMESTAMP WHERE id=?', (dataset_id,))
        return {'ok': True, 'message': 'Dataset removed from the workspace. Existing test history is retained.'}

    @app.delete('/api/runs/{run_id}')
    def delete_run(run_id: str):
        run = one('SELECT status FROM runs WHERE id=? AND deleted_at IS NULL', (run_id,))
        if run['status'] not in ('cancelled', 'completed', 'completed_with_errors'):
            raise HTTPException(409, 'Only completed or cancelled runs can be removed')
        with worker_lock(store, run_id) as acquired:
            if not acquired:
                raise HTTPException(409, 'The cancelled worker is still finishing; try again shortly')
            store.execute('UPDATE runs SET deleted_at=CURRENT_TIMESTAMP WHERE id=?', (run_id,))
        return {'ok': True, 'message': 'Run removed. Audit and historical records are retained.'}

    @app.get('/api/bootstrap')
    def bootstrap():
        applications = store.rows('SELECT * FROM applications WHERE deleted_at IS NULL ORDER BY name')
        for row in applications:
            row['config'] = json.loads(row['config'])
        metrics = [{'name': name, 'requires': requirement, 'description': description,
                    'implementation': metric_implementation(name), 'default': name in all_deepeval_metrics(), 'legacy': name == 'Feedback hallucination'}
                   for name, (requirement, description) in CRITERIA.items()]
        metrics += [{'name': name, 'requires': ', '.join(fields), 'description': 'Native DeepEval metric for any connected tool',
                     'implementation': metric_implementation(name), 'default': not name.startswith('RAG '), 'legacy': name.startswith('RAG ')}
                    for name, (_, fields) in NATIVE_METRICS.items()]
        metrics += [{'name': name, 'requires': required, 'description': 'Supplementary deterministic check',
                     'implementation': metric_implementation(name), 'default': False, 'legacy': False}
                    for name, required in [('Score accuracy', 'Approved score_range'), ('Exact concept labels', 'Approved expected_concepts'), ('JSON output', 'JSON response expected')]]
        return {'applications': applications, 'categories': CATEGORIES, 'metrics': metrics}

    @app.get('/api/dashboard')
    def dashboard():
        results = store.rows('SELECT x.* FROM results x JOIN runs r ON r.id=x.run_id JOIN applications a ON a.id=r.application_id WHERE r.deleted_at IS NULL AND a.deleted_at IS NULL')
        quality, score_checks = [], []
        for result in results:
            for name, metric in json.loads(result['metrics'] or '{}').items():
                if isinstance(metric.get('score'), (int, float)):
                    quality.append(metric.get('quality_score', metric['score']))
                    if name == 'Score accuracy':
                        score_checks.append(metric['score'])
        return {'technologies': store.rows('SELECT COUNT(*) n FROM technologies t JOIN applications a ON a.id=t.application_id WHERE a.deleted_at IS NULL')[0]['n'], 'questions': store.rows('SELECT COUNT(*) n FROM questions q JOIN technologies t ON t.id=q.technology_id JOIN applications a ON a.id=t.application_id WHERE a.deleted_at IS NULL')[0]['n'], 'tested_questions': len({json.loads(r['snapshot'])['question_id'] for r in results if r['actual']}), 'pending': sum(r['state'] == 'pending' for r in results), 'failed': sum(r['state'] == 'failed' for r in results), 'errors': sum(r['state'] in ('execution_error', 'evaluation_error', 'needs_review') for r in results), 'average_quality': sum(quality) / len(quality) if quality else None, 'candidate_score_accuracy': sum(score_checks) / len(score_checks) if score_checks else None, 'runs': store.rows('SELECT r.*,a.name application FROM runs r JOIN applications a ON a.id=r.application_id WHERE r.deleted_at IS NULL AND a.deleted_at IS NULL ORDER BY r.rowid DESC LIMIT 20'), 'technologies_breakdown': store.rows('SELECT t.name,a.name application,COUNT(q.id) questions FROM technologies t JOIN applications a ON a.id=t.application_id LEFT JOIN questions q ON q.technology_id=t.id WHERE a.deleted_at IS NULL GROUP BY t.id'), 'states': store.rows('SELECT x.state,COUNT(*) count FROM results x JOIN runs r ON r.id=x.run_id JOIN applications a ON a.id=r.application_id WHERE r.deleted_at IS NULL AND a.deleted_at IS NULL GROUP BY x.state')}

    @app.post('/api/connections')
    def save_connection(body: dict):
        name = str(body.get('name', '')).strip()
        if not name:
            raise ValueError('Application name is required')
        config = dict(body['config'])
        if body['kind'] == 'api' and not config.get('submit_path'):
            parsed = urlparse(config.get('url', ''))
            config['submit_path'] = parsed.path or '/'
            config['url'] = f'{parsed.scheme}://{parsed.netloc}'
        if body.get('api_token'):
            env_name = 'EVO_API_TOKEN_' + hashlib.sha256(name.encode()).hexdigest()[:16]
            os.environ[env_name] = str(body['api_token'])
            config['token_env'] = env_name
        return {'id': store.save_application(name, body['kind'], config)}

    @app.post('/api/connections/{app_id}/diagnostics')
    def connection_diagnostics(app_id: str):
        record = application(app_id)
        connector = make_connector(record['kind'], record['config'])
        try:
            connector.connect()
            return {'capabilities': connector.discover_capabilities(), 'selectors': connector.diagnostics() if hasattr(connector, 'diagnostics') else {}}
        finally:
            connector.close()

    @app.get('/api/connections/{app_id}/interview-options')
    def interview_options(app_id: str, domain_id: int | None = None):
        from .interview_api import InterviewAPIConnector
        record = application(app_id)
        if urlparse(record['config'].get('url', '')).netloc != '50.62.181.23:8501':
            raise ValueError('This preset is for the configured AI Interview server')
        connector = InterviewAPIConnector(record['config'])
        try:
            connector.connect()
            return connector.options(domain_id)
        finally:
            connector.close()

    @app.post('/api/connections/{app_id}/interview-setup')
    def interview_setup(app_id: str, body: dict):
        from .interview_api import InterviewAPIConnector
        record = application(app_id)
        options = interview_options(app_id, int(body['domain_id']))
        domain = int(body['domain_id'])
        level = int(body['level_rank'])
        technologies = [int(t) for t in body['technology_ids']]
        if domain not in {d['DomainID'] for d in options['domains']} or level not in {p['LevelRank'] for p in options['proficiencies']}:
            raise ValueError('Choose a current domain and proficiency level')
        if not technologies or not set(technologies) <= {t['TechnologyID'] for t in options['technologies']}:
            raise ValueError('Choose technologies belonging to this domain')
        practice = body.get('practice_type', 'Technical')
        if practice not in ('Technical', 'Non-Technical', 'Mixed'):
            raise ValueError('Invalid practice type')
        config = {k: v for k, v in record['config'].items() if k in ('url', 'timeout', 'certificate_exception_origin', 'ca_bundle', 'token_env')}
        config.update(adapter='interview_api', domain_id=domain, level_rank=level,
                      technology_ids=technologies, practice_type=practice, timeout=120)
        connector = InterviewAPIConnector(config)
        try:
            connector.connect()
            records, totals = connector.catalog()
        finally:
            connector.close()
        store.save_application(record['name'], 'api', config)
        result = store.import_catalog(app_id, records, 'interview session API', totals)
        for question in store.questions(app_id):
            if question['text'] == 'What is the difference between an INNER JOIN and a LEFT JOIN in SQL?':
                reference = store.reference(question['id'])
                content = json.loads(reference['content'])
                if not content.get('expected_answer') and not content.get('concepts'):
                    content.update(expected_answer='INNER JOIN returns matching rows from both tables. LEFT JOIN retains all left rows, with matching right rows or NULL for nonmatches.',
                        concepts=['INNER JOIN returns only matching rows from both tables.', 'LEFT JOIN retains all left rows and uses NULL for unmatched right columns.'],
                        reference_note='Locally authored starter reference. Review before approval; not an official server rubric.')
                    store.revise_chunk(reference['id'], content)
        return {'catalog': result, 'questions': len(records)}

    @app.post('/api/connections/{app_id}/interview-first-test')
    def interview_first_test(app_id: str):
        record = application(app_id)
        if record['config'].get('adapter') != 'interview_api':
            raise ValueError('Configure interview automation first')
        question_text = 'What is the difference between an INNER JOIN and a LEFT JOIN in SQL?'
        questions = [q for q in store.questions(app_id) if q['text'] == question_text and str(q['technology_external_id']) == '4']
        if len(questions) != 1:
            raise ValueError('Select Data Analytics and SQL, then save to collect the JOIN question for this starter test')
        # No invented rubric or score range: GEval judges the feedback against the actual input.
        answer = ('An INNER JOIN returns only matching rows from both tables. A LEFT JOIN returns every row '
                  'from the left table and matching rows from the right table. Where no match exists, '
                  'the right-table columns contain NULL.')
        dataset = store.create_dataset(app_id, 'First automated SQL interview',
            [{'question_id': questions[0]['id'], 'candidate_input': answer}], source='authored starter case')
        cases = store.rows('SELECT id FROM cases WHERE dataset_id=?', (dataset,))
        run_id = store.create_run(app_id, [c['id'] for c in cases],
            {'metrics': all_deepeval_metrics(), 'judge_model': settings['judge_model'],
             'threshold': .5, 'batch_size': 1, 'interval': 1, 'connect_attempts': 1})
        started = bool(settings['openai_key'])
        if started:
            start_worker(run_id)
        return {'run_id': run_id, 'dataset_id': dataset, 'started': started,
                'message': 'One live answer will be submitted and evaluated.' if started else
                'Test prepared. Save your OpenAI key in Settings, then Resume this pending run. No answer has been submitted.'}

    @app.post('/api/connections/{app_id}/synchronize')
    def synchronize(app_id: str, body: dict):
        record = application(app_id)
        config = record['config']
        if record['kind'] == 'import':
            raise ValueError('Use Import catalog for this offline connection')
        if record['kind'] in ('browser', 'interview'):
            keys = ('technology_select', 'technology_options', 'catalog_rows') if body.get('technologies_only') else ('catalog_rows', 'question')
            if not any(config.get(k) for k in keys):
                raise ValueError('This website needs a one-time control mapping before discovery. Use Check connection, or choose Import catalog to continue now.')
        elif not config.get('catalog_path'):
            raise ValueError('Add an authorized catalog API path in Advanced options, or use Import catalog.')
        def action(progress):
            connector = make_connector(record['kind'], record['config'])
            try:
                progress(.1, 'Connecting to application')
                connector.connect()
                if body.get('technologies_only'):
                    technologies = connector.technologies()
                    store.import_technologies(app_id, technologies)
                    return {'technologies': technologies}
                progress(.3, 'Collecting authorized catalog or observed questions')
                records, totals = connector.catalog()
                return store.import_catalog(app_id, records, record['kind'], totals)
            finally:
                connector.close()
        return job('Catalog synchronization', action)

    @app.post('/api/connections/{app_id}/login')
    def start_login(app_id: str):
        record = application(app_id)
        if record['kind'] not in ('browser', 'interview'):
            raise ValueError('Browser sign-in is only available for website connections')
        if app_id in login_sessions:
            raise HTTPException(409, 'A sign-in window is already open')
        event = threading.Event()
        job_id = uid()
        login_sessions[app_id] = (event, job_id)
        store.execute('INSERT INTO jobs(id,kind,message) VALUES(?,?,?)', (job_id, 'Browser sign-in', 'Opening a browser for your test-account sign-in'))
        def login_work():
            config = dict(record['config'], headless=False)
            config.pop('storage_state_env', None)
            config.pop('login', None)
            connector = make_connector(record['kind'], config)
            try:
                connector.connect()
                store.execute("UPDATE jobs SET state='awaiting_login',message='Sign in using the browser window, then choose Finish sign-in in E.V.O.' WHERE id=?", (job_id,))
                if not event.wait(600):
                    raise ValueError('Sign-in window timed out after 10 minutes')
                folder = Path(store.path).parent / '.auth'
                folder.mkdir(exist_ok=True)
                state_path = folder / (app_id + '.json')
                connector.context.storage_state(path=str(state_path))
                env_name = 'EVO_BROWSER_STATE_' + app_id.replace('-', '_')
                os.environ[env_name] = str(state_path)
                record['config']['storage_state_env'] = env_name
                store.save_application(record['name'], record['kind'], record['config'])
                store.execute("UPDATE jobs SET state='completed',progress=1,message='Sign-in session saved locally. Passwords were not stored in connection settings.' WHERE id=?", (job_id,))
            except Exception as exc:
                store.execute("UPDATE jobs SET state='failed',message=? WHERE id=?", (type(exc).__name__ + ': could not complete browser sign-in; check browser permissions and connection settings', job_id))
            finally:
                connector.close()
                login_sessions.pop(app_id, None)
        threading.Thread(target=login_work, daemon=True, name='evo-sign-in').start()
        return {'job_id': job_id}

    @app.post('/api/connections/{app_id}/login/complete')
    def finish_login(app_id: str):
        session = login_sessions.get(app_id)
        if not session:
            raise HTTPException(409, 'No sign-in window is active; start sign-in again')
        state = one('SELECT state FROM jobs WHERE id=?', (session[1],))['state']
        if state != 'awaiting_login':
            raise HTTPException(409, 'The sign-in browser is not ready yet. Check its progress message.')
        session[0].set()
        return {'ok': True}

    @app.get('/api/catalog/{app_id}')
    def catalog(app_id: str):
        application(app_id)
        return {'questions': store.questions(app_id), 'technologies': store.rows('SELECT * FROM technologies WHERE application_id=? ORDER BY name', (app_id,)), 'discoveries': [{**r, 'statistics': json.loads(r['statistics'])} for r in store.rows('SELECT * FROM discoveries WHERE application_id=? ORDER BY rowid DESC LIMIT 5', (app_id,))]}

    @app.post('/api/catalog/{app_id}/import')
    def import_catalog(app_id: str, body: dict):
        application(app_id)
        return store.import_catalog(app_id, body['records'], 'authorized import')

    @app.post('/api/imports/parse')
    def parse_import(file: UploadFile = File(...)):
        data = file.file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('Import is larger than 20 MB')
        return parse_records(data.decode('utf-8-sig'), file.filename)

    @app.get('/api/chunks')
    def chunks(kind: str = 'structured', app_id: str = ''):
        sql = 'SELECT c.*,q.text question,t.name technology FROM chunks c LEFT JOIN questions q ON q.id=c.question_id LEFT JOIN technologies t ON t.id=q.technology_id WHERE c.kind=?'
        params = [kind]
        if kind == 'document':
            sql += ' AND c.active=1'
        if app_id and kind == 'structured':
            sql += ' AND t.application_id=?'
            params.append(app_id)
        return [{**row, 'content': json.loads(row['content'])} for row in store.rows(sql + ' ORDER BY c.rowid DESC', params)]

    @app.post('/api/chunks/{chunk_id}/version')
    def revise_chunk(chunk_id: str, body: dict):
        return {'id': store.revise_chunk(chunk_id, body['content'], body.get('validation', 'unverified'))}

    @app.post('/api/chunks/{chunk_id}/deactivate')
    def deactivate_chunk(chunk_id: str):
        one('SELECT id FROM chunks WHERE id=?', (chunk_id,))
        store.execute('UPDATE chunks SET active=0 WHERE id=?', (chunk_id,))
        return {'ok': True}

    @app.post('/api/chunks/{chunk_id}/generate')
    def generate_reference(chunk_id: str):
        row = one('SELECT c.*,q.text question FROM chunks c JOIN questions q ON q.id=c.question_id WHERE c.id=?', (chunk_id,))
        def action(progress):
            content = propose_reference(row['question'], settings['judge_model'], settings['openai_key'])
            return {'id': store.revise_chunk(chunk_id, content, 'generated')}
        return job('Independent reference proposal', action)

    @app.get('/api/datasets/{app_id}')
    def datasets(app_id: str):
        return store.rows('SELECT d.*,COUNT(c.id) cases FROM datasets d LEFT JOIN cases c ON c.dataset_id=d.id WHERE d.application_id=? AND d.deleted_at IS NULL GROUP BY d.id ORDER BY d.rowid DESC', (app_id,))

    @app.post('/api/datasets/{app_id}/import')
    def import_dataset(app_id: str, body: dict):
        return {'id': store.create_dataset(app_id, body['name'], body['cases'])}

    @app.post('/api/datasets/{app_id}/generate')
    def generate_dataset(app_id: str, body: dict):
        questions = [q for q in store.questions(app_id) if q['id'] in body['question_ids']]
        if not questions:
            raise ValueError('Select at least one question')
        blocked = []
        for question in questions:
            ref = store.reference(question['id'])
            if not ref or ref['validation'] != 'approved':
                blocked.append(question['text'])
        if blocked:
            raise ValueError('Reference approval needed for: ' + '; '.join(blocked) +
                '. Open Reference library, review the latest version, tick the approval box, and Save new version. Then select those questions again.')
        def action(progress):
            cases = []
            for index, question in enumerate(questions):
                progress(index / len(questions), f'Generating answers for question {index + 1}/{len(questions)}')
                cases.extend(generate_cases(question, store.reference(question['id']), body['categories'], int(body.get('count', 1)), settings['judge_model'], settings['openai_key']))
            return {'id': store.create_dataset(app_id, body['name'], cases, 'generated-unverified')}
        return job('Candidate dataset generation', action)

    @app.get('/api/dataset/{dataset_id}/cases')
    def cases(dataset_id: str):
        one('SELECT id FROM datasets WHERE id=? AND deleted_at IS NULL', (dataset_id,))
        return [{**row, 'content': json.loads(row['content'])} for row in store.rows('SELECT c.*,q.text question,t.name technology FROM cases c JOIN questions q ON q.id=c.question_id JOIN technologies t ON t.id=q.technology_id WHERE dataset_id=? ORDER BY c.rowid', (dataset_id,))]

    @app.post('/api/case-actions/{action}')
    def bulk_cases(action: str, body: dict):
        from .evaluation import propose_case_expectation
        dataset = one('SELECT * FROM datasets WHERE id=? AND deleted_at IS NULL', (body['dataset_id'],))
        application(dataset['application_id'])
        items = body.get('items', [])
        if not items or len(items) > 200 or len({i['id'] for i in items}) != len(items):
            raise ValueError('Select between 1 and 200 distinct test cases')
        rows = []
        for item in items:
            row = one('SELECT c.*,q.text question FROM cases c JOIN questions q ON q.id=c.question_id WHERE c.id=? AND c.dataset_id=?', (item['id'], dataset['id']))
            if json.loads(row['content']) != item.get('content') or (action == 'approve' and row['validation'] == 'approved'):
                raise HTTPException(409, 'Selected cases changed or are already approved. Refresh and review them again.')
            rows.append(row)
        if action == 'approve':
            if body.get('reviewed') is not True:
                raise ValueError('Confirm that you reviewed the selected content before approval')
            with store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                for row in rows:
                    content = json.loads(row['content'])
                    if not any(content.get(k) for k in ('expected_output', 'score_range', 'expected_concepts')):
                        raise ValueError('Generate proposals or add expected outcomes before approval')
                    changed = db.execute("UPDATE cases SET validation='approved' WHERE id=? AND content=? AND validation=? AND EXISTS(SELECT 1 FROM datasets WHERE id=? AND deleted_at IS NULL)", (row['id'], row['content'], row['validation'], dataset['id'])).rowcount
                    if changed != 1:
                        raise ValueError('A case changed during review; refresh before approving')
                db.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset['id'],))
            for row in rows:
                store.record_change('APPROVE_CASE', row['id'])
            return {'approved': len(rows)}
        if action != 'generate':
            raise ValueError('Choose generate or approve')
        if not settings['openai_key']:
            raise ValueError('Add your OpenAI key in Settings before generating proposals')
        for row in rows:
            row['reference'] = store.reference(row['question_id'])
            if not row['reference'] or row['reference']['validation'] != 'approved':
                raise ValueError('Approve the question references before proposing expected test-case feedback')
        def action_job(progress):
            saved, errors = [], []
            for index, row in enumerate(rows):
                progress(index / len(rows), f'Generating case proposal {index + 1} of {len(rows)}')
                try:
                    content = json.loads(row['content'])
                    content['expected_output'] = propose_case_expectation(row['question'], content['candidate_input'], json.loads(row['reference']['content']), settings['judge_model'], settings['openai_key'])
                    with store.connection() as db:
                        db.execute('BEGIN IMMEDIATE')
                        latest = db.execute('SELECT id FROM chunks WHERE question_id=? AND active=1 ORDER BY version DESC LIMIT 1', (row['question_id'],)).fetchone()
                        if not latest or latest['id'] != row['reference']['id']:
                            raise ValueError('Reference changed during generation')
                        changed = db.execute("UPDATE cases SET content=?,validation='generated',chunk_id=? WHERE id=? AND content=? AND validation=? AND EXISTS(SELECT 1 FROM datasets WHERE id=? AND deleted_at IS NULL)", (encode(content), row['reference']['id'], row['id'], row['content'], row['validation'], dataset['id'])).rowcount
                        if changed != 1:
                            raise ValueError('Case changed during generation')
                        db.execute('UPDATE datasets SET version=version+1 WHERE id=?', (dataset['id'],))
                    store.record_change('GENERATE_CASE_PROPOSAL', row['id'])
                    saved.append(row['id'])
                except Exception as exc:
                    errors.append({'id': row['id'], 'error': type(exc).__name__ + ': proposal failed or content changed'})
            return {'saved': saved, 'errors': errors, 'message': f'{len(saved)} case proposals saved; {len(errors)} failed. Review the proposals and approve selected.'}
        return job('Test-case proposals', action_job)

    @app.post('/api/cases/{case_id}')
    def edit_case(case_id: str, body: dict):
        case = one('SELECT * FROM cases WHERE id=?', (case_id,))
        one('SELECT id FROM datasets WHERE id=? AND deleted_at IS NULL', (case['dataset_id'],))
        content = body['content']
        if content.get('question_id') != case['question_id'] or not isinstance(content.get('candidate_input'), str):
            raise ValueError('Keep the original question_id and provide a text candidate_input')
        validation = 'approved' if body.get('approved') else 'unverified'
        with store.connection() as db:
            db.execute('UPDATE cases SET content=?,validation=? WHERE id=?', (encode(content), validation, case_id))
            db.execute('UPDATE datasets SET version=version+1 WHERE id=?', (case['dataset_id'],))
        return {'ok': True}

    @app.get('/api/runs')
    def runs():
        return store.rows('SELECT r.*,a.name application,(SELECT COUNT(*) FROM results x WHERE x.run_id=r.id) total,(SELECT COUNT(*) FROM results x WHERE x.run_id=r.id AND x.state NOT IN (\'pending\',\'submitting\',\'captured\')) finished FROM runs r JOIN applications a ON a.id=r.application_id WHERE r.deleted_at IS NULL ORDER BY r.rowid DESC')

    @app.post('/api/runs')
    def create_run(body: dict):
        config = body['config']
        config['judge_model'] = settings['judge_model']
        if not config.get('metrics'):
            raise ValueError('Select at least one metric')
        supported = set(NATIVE_METRICS) | set(CRITERIA) | set(LOCAL_CHECKS)
        if any(name not in supported for name in config['metrics']):
            raise ValueError('Select supported DeepEval metrics or local checks')
        if not 1 <= int(config.get('batch_size', 25)) <= 10000 or not 0 <= float(config.get('interval', 1)) <= 60:
            raise ValueError('Invalid batch size or interval')
        run_id = store.create_run(body['application_id'], body['case_ids'], config)
        if body.get('start', True):
            start_worker(run_id)
        return {'id': run_id}

    @app.post('/api/runs/{run_id}/{action}')
    def control_run(run_id: str, action: str):
        one('SELECT id FROM runs WHERE id=?', (run_id,))
        if action == 'cloud-sync':
            status = one('SELECT status FROM runs WHERE id=?', (run_id,))['status']
            if status not in ('completed', 'completed_with_errors', 'cancelled'):
                raise ValueError('Finish or cancel the run before uploading its snapshot')
            if not settings['confident_key']:
                raise ValueError('Add your Confident AI key in Settings first')
            env = os.environ.copy()
            env['CONFIDENT_API_KEY'] = settings['confident_key']
            env['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
            env['CONFIDENT_OPEN_BROWSER'] = 'false'
            subprocess.Popen([sys.executable, '-m', 'evo_platform.cloud', '--db', store.path, '--run', run_id],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        elif action == 'pause':
            store.execute("UPDATE runs SET status='paused' WHERE id=? AND status='running'", (run_id,))
        elif action == 'cancel':
            store.execute("UPDATE runs SET status='cancelled' WHERE id=? AND status IN ('pending','running','paused','interrupted')", (run_id,))
        elif action == 'resume':
            start_worker(run_id)
        elif action == 'recover':
            recover(store, run_id)
        elif action == 'retry-evaluation':
            with worker_lock(store, run_id) as acquired:
                if not acquired:
                    raise HTTPException(409, 'Worker is still active')
                store.execute("UPDATE results SET state='captured' WHERE run_id=? AND state='evaluation_error' AND actual IS NOT NULL", (run_id,))
                store.execute("UPDATE runs SET status='interrupted' WHERE id=? AND status!='cancelled'", (run_id,))
                store.execute("UPDATE cloud_sync SET state='pending',dataset_uploaded=0,confident_link=NULL,message='Results are being re-evaluated' WHERE run_id=?", (run_id,))
            start_worker(run_id)
        else:
            raise HTTPException(404, 'Unknown action')
        return {'ok': True}

    @app.get('/api/runs/{run_id}/cloud-status')
    def cloud_status(run_id: str):
        one('SELECT id FROM runs WHERE id=?', (run_id,))
        rows = store.rows('SELECT * FROM cloud_sync WHERE run_id=?', (run_id,))
        return rows[0] if rows else {'state': 'pending', 'message': 'Cloud sync starts after evaluation completes'}

    @app.get('/api/runs/{run_id}/results')
    def results(run_id: str):
        return [{**r, 'snapshot': json.loads(r['snapshot']), 'actual': json.loads(r['actual'] or '{}'), 'metrics': json.loads(r['metrics'] or '{}')} for r in store.results(run_id)]

    @app.get('/api/runs/{run_id}/export')
    def export(run_id: str, format: str = 'json'):
        if format not in ('json', 'csv', 'pdf', 'docx'):
            raise ValueError('Choose JSON, CSV, PDF, or DOCX')
        one('SELECT id FROM runs WHERE id=?', (run_id,))
        if format in ('pdf', 'docx'):
            from .reports import report_bytes
            records = [{**r, 'question': r['snapshot']['question']} for r in results(run_id)]
            mime = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            return Response(report_bytes('E.V.O evaluation results', records, format), media_type=mime, headers={'Content-Disposition': f'attachment; filename="{run_id}.{format}"'})
        return Response(store.export_results(run_id, format), media_type='application/json' if format == 'json' else 'text/csv', headers={'Content-Disposition': f'attachment; filename="{run_id}.{format}"'})

    @app.get('/api/jobs')
    def jobs():
        return [{**r, 'result': json.loads(r['result']) if r['result'] else None} for r in store.rows('SELECT * FROM jobs WHERE dismissed_at IS NULL ORDER BY rowid DESC LIMIT 20')]

    @app.delete('/api/jobs')
    def clear_finished_jobs():
        count = store.execute("UPDATE jobs SET dismissed_at=CURRENT_TIMESTAMP WHERE dismissed_at IS NULL AND state IN ('completed','failed')")
        return {'removed': count}

    @app.delete('/api/jobs/{job_id}')
    def dismiss_job(job_id: str):
        one('SELECT id FROM jobs WHERE id=? AND dismissed_at IS NULL', (job_id,))
        count = store.execute("UPDATE jobs SET dismissed_at=CURRENT_TIMESTAMP WHERE id=? AND dismissed_at IS NULL AND state IN ('completed','failed')", (job_id,))
        if not count:
            raise HTTPException(409, 'Wait for this process to finish before removing it')
        return {'ok': True}

    @app.delete('/api/rag/documents/{document_id}')
    def remove_document(document_id: str):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM chunks WHERE document_id=? AND kind='document' AND active=1", (document_id,)).fetchone():
                raise HTTPException(404, 'Document not found')
            if db.execute("SELECT 1 FROM jobs WHERE document_id=? AND state NOT IN ('completed','failed')", (document_id,)).fetchone():
                raise HTTPException(409, 'This document is being used by a process. Wait for it to finish.')
            db.execute("UPDATE chunks SET active=0 WHERE document_id=? AND kind='document'", (document_id,))
        return {'ok': True, 'message': 'Document removed from local use. Existing evaluation snapshots are retained.'}

    @app.get('/api/settings')
    def get_settings():
        return {**{k: v for k, v in settings.items() if k not in ('openai_key', 'supabase_key', 'confident_key')}, 'confident_configured': bool(settings['confident_key']), 'openai_configured': bool(settings['openai_key']), 'supabase_configured': bool(settings['supabase_key'] and settings['supabase_url'])}

    @app.post('/api/settings')
    def save_settings(body: dict):
        for key in settings:
            if key in body and (body[key] or key not in ('openai_key', 'supabase_key', 'confident_key')):
                settings[key] = str(body[key])
        return {'ok': True, 'message': 'Saved for this server session. Use environment variables for persistent credentials.'}

    @app.get('/api/rag')
    def rag_data():
        documents = store.rows("SELECT document_id,COUNT(*) chunks FROM chunks WHERE kind='document' AND active=1 GROUP BY document_id")
        for doc in documents:
            first = one('SELECT content FROM chunks WHERE document_id=? LIMIT 1', (doc['document_id'],))
            doc['name'] = json.loads(first['content'])['metadata'].get('file_title', doc['document_id'])
        snapshots = store.rows('SELECT * FROM rag_snapshots ORDER BY rowid DESC')
        return {'documents': documents, 'snapshots': [{**r, 'goldens': json.loads(r['goldens']), 'metrics': json.loads(r['metrics'])} for r in snapshots]}

    @app.post('/api/rag/upload')
    def rag_upload(file: UploadFile = File(...), chunk_size: int = Form(1000), overlap: int = Form(200), sync_supabase: bool = Form(False)):
        from processDocuments import DocumentProcessor
        processor = DocumentProcessor(chunk_size, overlap)
        data = file.file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('The maximum document size is 20 MB')
        filename = Path(file.filename.replace('\\', '/')).name
        suffix = Path(filename).suffix.lower()
        if suffix not in ('.pdf', '.docx', '.txt', '.csv', '.xlsx'):
            raise ValueError('Supported files: PDF, DOCX, TXT, CSV, XLSX')
        document_id = hashlib.sha256(data + filename.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ('document' + suffix)
            path.write_bytes(data)
            text = processor.read_file(str(path))
        chunks = processor.chunk_text(text, filename)
        for chunk in chunks:
            chunk['metadata']['file_id'] = document_id
            store.save_document_chunk(chunk['text'], chunk['metadata'])
        warning = None
        if sync_supabase:
            from processDocuments import SupabaseChunkLoader
            loader = SupabaseChunkLoader(settings['supabase_url'], settings['supabase_key'], settings['supabase_table'])
            if not loader.insert_chunks(chunks):
                warning = 'Local chunks saved; Supabase upload failed. Check Supabase configuration.'
        return {'document_id': document_id, 'chunks': len(chunks), 'warning': warning}

    @app.post('/api/rag/synthesize')
    def rag_synthesize(body: dict):
        document_id = body['document_id']
        maximum = max(1, min(int(body.get('max_chunks', 10)), 100))
        chunks = store.rows("SELECT * FROM chunks WHERE document_id=? AND active=1 ORDER BY rowid LIMIT ?", (document_id, maximum))
        if not chunks:
            raise ValueError('Upload and select a document first')
        def action(progress):
            from deepeval.synthesizer import Synthesizer
            from .providers import openai_judge
            progress(.1, 'Generating reference Q&A with DeepEval')
            contents = [json.loads(chunk['content']) for chunk in chunks]
            name = contents[0]['metadata']['file_title']
            synthesizer = Synthesizer(model=openai_judge(settings['judge_model'], settings['openai_key']))
            goldens = synthesizer.generate_goldens_from_contexts(contexts=[[c['text']] for c in contents], max_goldens_per_context=max(1, min(20, int(body.get('target', 5))) // len(contents)), include_expected_output=True)
            rows = [{'doc': name, 'question': g.input, 'expected': g.expected_output, 'context': g.context or [], 'actual': ''} for g in goldens]
            snapshot_id = uid()
            store.execute('INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES(?,?,?,?)', (snapshot_id, name + ' · generated goldens', encode(rows), '{}'))
            return {'id': snapshot_id, 'goldens': len(rows)}
        return job('RAG golden synthesis', action, document_id=document_id)

    @app.post('/api/rag/snapshots/{snapshot_id}')
    def edit_rag_snapshot(snapshot_id: str, body: dict):
        old = one('SELECT * FROM rag_snapshots WHERE id=?', (snapshot_id,))
        for record in body['goldens']:
            if not isinstance(record.get('question'), str) or not isinstance(record.get('expected'), str):
                raise ValueError('Each golden needs a question and expected answer')
        new_id = uid()
        store.execute('INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES(?,?,?,?)', (new_id, old['label'] + ' · reviewed', encode(body['goldens']), '{}'))
        return {'id': new_id}

    @app.post('/api/rag/evaluate')
    def rag_evaluate(body: dict):
        snapshot = one('SELECT * FROM rag_snapshots WHERE id=?', (body['snapshot_id'],))
        if not settings['webhook_url']:
            raise ValueError('Configure the RAG endpoint in Settings')
        def action(progress):
            import requests
            from .providers import openai_judge
            goldens = json.loads(snapshot['goldens'])
            judge = openai_judge(settings['judge_model'], settings['openai_key'])
            aggregate = {}
            for index, golden in enumerate(goldens):
                progress(index / max(1, len(goldens)), f'Evaluating RAG case {index + 1}/{len(goldens)}')
                response = requests.post(settings['webhook_url'], json={'question': golden['question']}, timeout=60)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    payload = payload[0] if payload else {}
                actual = {'output': payload.get('answer') or payload.get('output') or '', 'retrieval_context': payload.get('retrieval_context')}
                case = {'question': golden['question'], 'content': encode({'candidate_input': golden['question'], 'expected_output': golden['expected'], 'context': golden.get('context')}), 'reference': None}
                metrics = evaluate_output(case, actual, {'metrics': body['metrics'], 'threshold': body.get('threshold', .5)}, judge)
                golden.update(actual=actual['output'], quality_metrics=metrics)
                for name, metric in metrics.items():
                    if metric.get('score') is not None:
                        aggregate.setdefault(name, []).append(metric['score'])
            new_id = uid()
            store.execute('INSERT INTO rag_snapshots(id,label,goldens,metrics) VALUES(?,?,?,?)', (new_id, snapshot['label'] + ' · evaluated', encode(goldens), encode(aggregate)))
            return {'id': new_id, 'metrics': aggregate}
        return job('RAG evaluation', action)

    @app.get('/api/rag/snapshots/{snapshot_id}/export')
    def export_rag(snapshot_id: str, format: str = 'json'):
        row = one('SELECT * FROM rag_snapshots WHERE id=?', (snapshot_id,))
        if format == 'json':
            return Response(row['goldens'], media_type='application/json', headers={'Content-Disposition': f'attachment; filename="{snapshot_id}.json"'})
        from .reports import report_bytes
        content = report_bytes('E.V.O RAG evaluation', json.loads(row['goldens']), format)
        mime = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return Response(content, media_type=mime, headers={'Content-Disposition': f'attachment; filename="{snapshot_id}.{format}"'})

    app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'web' / 'index.html')

    return app


app = create_app()
