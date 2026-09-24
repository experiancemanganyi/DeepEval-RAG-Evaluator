"""Configurable connectors. No interview-specific selectors are guessed."""
import json
import os
import re
from urllib.parse import urlparse, urljoin
from .store import normalize


class ConnectorError(RuntimeError):
    pass


class QuestionMismatch(ConnectorError):
    def __init__(self, question, external_id=None):
        super().__init__('Displayed question differs from the requested case; match another stored case before submitting')
        self.question = question
        self.external_id = external_id


def origin(url):
    parsed = urlparse(url)
    return f'{parsed.scheme}://{parsed.netloc}'


def validate_config(kind, config):
    if kind not in ('import', 'api', 'browser', 'interview'):
        raise ValueError('Unknown connector kind')
    if kind == 'import':
        return
    url = urlparse(config.get('url', ''))
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query:
        raise ValueError('Use an HTTP(S) base URL without embedded credentials or query strings.')
    if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Remote connections require HTTPS.')
    for key in ('password', 'token', 'api_key', 'headers', 'cookies', 'storage_state'):
        if key in config:
            raise ValueError(f'{key} must not be stored in connection settings; use environment variable references.')
    def reject_nested_secrets(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in ('password', 'token', 'api_key', 'client_secret', 'authorization', 'cookies', 'storage_state'):
                    raise ValueError('Use credential environment references instead of raw secrets in connection settings')
                reject_nested_secrets(child)
        elif isinstance(value, list):
            for child in value:
                reject_nested_secrets(child)
    reject_nested_secrets(config)
    if not 1 <= float(config.get('timeout', 60)) <= 600:
        raise ValueError('Timeout must be 1–600 seconds')
    exception = config.get('certificate_exception_origin')
    if exception and exception != origin(config['url']):
        raise ValueError('Certificate exception must match the exact configured origin')


class Connector:
    def __init__(self, config):
        self.config = config

    def connect(self):
        return self

    def authenticate(self):
        """Credentials are resolved only from local environment references."""

    def discover_capabilities(self):
        return {'catalog': False, 'question_selection': False, 'complete_coverage': False}

    def catalog(self):
        raise ConnectorError('No authorized catalog endpoint or browser catalog mapping configured')

    def technologies(self):
        records, _ = self.catalog()
        unique = {}
        for record in records:
            name = record['technology']
            external = str(record.get('technology_id') or normalize(name))
            unique[external] = {'id': external, 'name': name}
        return list(unique.values())

    def start_session(self, snapshot):
        pass

    def submit(self, snapshot, key):
        raise NotImplementedError

    def close(self):
        pass


class ImportedConnector(Connector):
    def submit(self, snapshot, key):
        case = json.loads(snapshot['content'])
        if 'actual' not in case:
            raise ConnectorError('Imported case has no actual output')
        actual = case['actual']
        return actual if isinstance(actual, dict) else {'output': str(actual)}


class APIConnector(Connector):
    def connect(self):
        import requests
        self.session = requests.Session()
        self.authenticate()
        return self

    def authenticate(self):
        env = self.config.get('token_env')
        if env:
            token = os.getenv(env)
            if not token:
                raise ConnectorError('The configured token environment variable is missing')
            self.session.headers['Authorization'] = 'Bearer ' + token

    def request(self, method, path, **kwargs):
        url = urljoin(self.config['url'].rstrip('/') + '/', path)
        if origin(url) != origin(self.config['url']):
            raise ConnectorError('Cross-origin API requests are blocked')
        verify = self.config.get('ca_bundle') or True
        if self.config.get('certificate_exception_origin') == origin(url):
            verify = False  # Explicit per-request, origin-bound user exception.
        response = self.session.request(method, url, timeout=float(self.config.get('timeout', 60)), verify=verify, allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            raise ConnectorError('API redirect blocked; configure the final authorized endpoint')
        response.raise_for_status()
        return response.json()

    def discover_capabilities(self):
        return {'catalog': bool(self.config.get('catalog_path')), 'question_selection': True, 'complete_coverage': 'Only with authoritative catalog totals'}

    def catalog(self):
        if not self.config.get('catalog_path'):
            return super().catalog()
        records, totals, visited = [], None, set()
        path = self.config['catalog_path']
        for _ in range(int(self.config.get('max_pages', 100))):
            if path in visited:
                raise ConnectorError('Catalog pagination repeated a page')
            visited.add(path)
            payload = self.request('GET', path)
            if isinstance(payload, list):
                records.extend(payload)
                break
            records.extend(payload['questions'])
            if payload.get('totals') is not None:
                totals = payload['totals']
            path = payload.get('next')
            if not path:
                break
        else:
            raise ConnectorError('Catalog page limit reached; coverage is incomplete')
        return records, totals

    def submit(self, snapshot, key):
        case = json.loads(snapshot['content'])
        payload = {'question_id': snapshot['external_id'], 'question': snapshot['question'], 'technology': snapshot['technology_external_id'], 'answer': case['candidate_input']}
        # This header is advisory. We never automatically retry POST, even if supported.
        actual = self.request('POST', self.config.get('submit_path', ''), json=payload, headers={'Idempotency-Key': key})
        mapping = self.config.get('response_fields', {})
        return {field: actual.get(mapping.get(field, field)) for field in ('output', 'score', 'concepts', 'feedback', 'question_id', 'retrieval_context')}

    def close(self):
        if hasattr(self, 'session'):
            self.session.close()


class BrowserConnector(Connector):
    def connect(self):
        from playwright.sync_api import sync_playwright
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=self.config.get('headless', True), channel=self.config.get('browser_channel') or None)
            kwargs = {}
            state_env = self.config.get('storage_state_env')
            if state_env:
                state_path = os.getenv(state_env)
                if not state_path:
                    raise ConnectorError('Authenticated browser state environment variable is missing')
                kwargs['storage_state'] = state_path
            exception = self.config.get('certificate_exception_origin')
            kwargs['ignore_https_errors'] = bool(exception)
            self.context = self.browser.new_context(**kwargs)
            if exception:
                # A fresh context is restricted to this origin, including subresources.
                self.context.route('**/*', lambda route: route.continue_() if origin(route.request.url) == exception else route.abort())
                websocket_origin = exception.replace('https://', 'wss://').replace('http://', 'ws://')
                self.context.route_web_socket('**/*', lambda socket: socket.connect_to_server() if origin(socket.url) == websocket_origin else socket.close())
            self.page = self.context.new_page()
            self.page.set_default_timeout(float(self.config.get('timeout', 60)) * 1000)
            self.page.goto(self.config['url'], wait_until='domcontentloaded')
            self.authenticate()
            return self
        except Exception:
            self.close()
            raise

    def authenticate(self):
        login = self.config.get('login', {})
        if not login:
            return
        for field in ('username', 'password'):
            value = os.getenv(login.get(field + '_env', ''))
            if not value:
                raise ConnectorError('Login environment variable is missing')
            self.page.locator(login[field + '_selector']).fill(value)
        self.page.locator(login['submit_selector']).click()
        self.page.locator(login['authenticated_selector']).wait_for(state='visible')

    def discover_capabilities(self):
        return {'catalog': bool(self.config.get('catalog_rows')), 'observations': bool(self.config.get('question')), 'technology_discovery': bool(self.config.get('technology_select') or self.config.get('technology_options')), 'question_selection': bool(self.config.get('question_select')), 'complete_coverage': False}

    def technologies(self):
        if self.config.get('technology_select'):
            options = self.page.locator(self.config['technology_select']).locator('option')
            return options.evaluate_all('(items) => items.filter(e => !e.disabled && e.value).map(e => ({id:e.value,name:e.textContent.trim()}))')
        if self.config.get('technology_options'):
            if self.config.get('technology_open'):
                self.page.locator(self.config['technology_open']).click()
            self.page.locator(self.config['technology_options']).first.wait_for(state='visible')
            return [{'id': normalize(option.inner_text()), 'name': option.inner_text()} for option in self.page.locator(self.config['technology_options']).all()]
        return super().technologies()

    def select_technology(self, name):
        if self.config.get('technology_select'):
            self.page.locator(self.config['technology_select']).select_option(label=name)
        elif self.config.get('technology_options'):
            self.page.locator(self.config['technology_open']).click()
            self.page.locator(self.config['technology_options']).filter(has_text=re.compile('^' + re.escape(name) + '$')).click()

    def diagnostics(self):
        selectors = {key: value for key, value in self.config.items() if key in ('input', 'submit', 'response', 'completion', 'question', 'score', 'feedback', 'technology_select', 'question_select') and value}
        matches = {key: {'matches': self.page.locator(value).count()} for key, value in selectors.items()}
        controls = self.page.locator('input,textarea,button,select,[role="combobox"],[aria-live],[role="log"]').evaluate_all('''(items) => items.filter(e=>e.getClientRects().length && e.getAttribute('type')!=='password').map(e=>({tag:e.tagName,id:e.id,role:e.getAttribute('role'),label:e.getAttribute('aria-label') || e.labels?.[0]?.innerText || (e.tagName==='BUTTON'?e.innerText:''),placeholder:e.getAttribute('placeholder'),type:e.getAttribute('type'),live:e.getAttribute('aria-live'),selector:e.id?'#'+CSS.escape(e.id):e.getAttribute('data-testid')?'[data-testid='+JSON.stringify(e.getAttribute('data-testid'))+']':e.getAttribute('aria-label')?'[aria-label='+JSON.stringify(e.getAttribute('aria-label'))+']':e.getAttribute('placeholder')?'[placeholder='+JSON.stringify(e.getAttribute('placeholder'))+']':null}))''')
        suggestions = {}
        candidates = {
            'input': [c for c in controls if c['tag'] == 'TEXTAREA' or (c['tag'] == 'INPUT' and c['type'] in ('text', 'search'))],
            'submit': [c for c in controls if c['tag'] == 'BUTTON' and any(word in (c['label'] or '').lower() for word in ('send', 'submit', 'evaluate', 'ask'))],
            'response': [c for c in controls if c['live'] or c['role'] == 'log'],
        }
        for field, options in candidates.items():
            usable = [c for c in options if c['selector'] and self.page.locator(c['selector']).count() == 1]
            if len(usable) == 1:
                suggestions[field] = usable[0]['selector']
        return {**matches, 'visible_control_attributes': controls, 'suggested_controls': suggestions, 'needs_confirmation': 'Confirm suggestions and a reliable completion indicator before live submission.'}

    def catalog(self):
        row_selector = self.config.get('catalog_rows')
        if not row_selector:
            if self.config.get('question'):
                return self.observe_questions(), None
            return super().catalog()
        records, seen_pages = [], set()
        for _ in range(int(self.config.get('max_pages', 100))):
            self.page.locator(row_selector).first.wait_for(state='visible')
            page_records = []
            for row in self.page.locator(row_selector).all():
                page_records.append({field: row.locator(selector).inner_text() for field, selector in self.config['catalog_fields'].items()})
            marker = json.dumps(page_records, sort_keys=True)
            if marker in seen_pages:
                raise ConnectorError('Catalog repeated a page; completeness cannot be established')
            seen_pages.add(marker)
            records.extend(page_records)
            next_selector = self.config.get('catalog_next')
            if not next_selector or not self.page.locator(next_selector).is_visible() or not self.page.locator(next_selector).is_enabled():
                return records, None
            previous = self.page.locator(row_selector).all_text_contents()
            self.page.locator(next_selector).click()
            self.page.wait_for_function('(a) => JSON.stringify(Array.from(document.querySelectorAll(a.s)).map(e=>e.textContent)) !== JSON.stringify(a.old)', arg={'s': row_selector, 'old': previous})
        raise ConnectorError('Browser catalog page limit reached')

    def observe_questions(self):
        """Read normal UI flow, bounded and explicitly incomplete; never submit dummy answers."""
        technologies = self.technologies()
        records = []
        for technology in technologies:
            for _ in range(min(10, max(1, int(self.config.get('observation_sessions', 1))))):
                if self.config.get('reset'):
                    self.page.locator(self.config['reset']).click()
                self.select_technology(technology['name'])
                if self.config.get('start'):
                    self.page.locator(self.config['start']).click()
                seen = set()
                for _ in range(min(500, max(1, int(self.config.get('max_questions_per_session', 100))))):
                    locator = self.page.locator(self.config['question'])
                    locator.wait_for(state='visible')
                    question = locator.inner_text()
                    if question in seen:
                        break
                    seen.add(question)
                    record = {'technology': technology['name'], 'technology_id': technology['id'], 'question': question}
                    if self.config.get('question_id_attribute'):
                        record['question_id'] = locator.get_attribute(self.config['question_id_attribute'])
                    if self.config.get('difficulty'):
                        record['difficulty'] = self.page.locator(self.config['difficulty']).inner_text()
                    records.append(record)
                    next_selector = self.config.get('next_question')
                    if not next_selector or not self.page.locator(next_selector).is_visible() or not self.page.locator(next_selector).is_enabled():
                        break
                    self.page.locator(next_selector).click()
                    self.page.wait_for_function('(a) => document.querySelector(a.selector)?.innerText !== a.previous', arg={'selector': self.config['question'], 'previous': question})
        return records

    def start_session(self, snapshot):
        if self.config.get('reset'):
            self.page.locator(self.config['reset']).click()
        self.select_technology(snapshot['technology'])
        if self.config.get('question_select'):
            self.page.locator(self.config['question_select']).select_option(value=snapshot['external_id'])
        if self.config.get('start'):
            self.page.locator(self.config['start']).click()
        if self.config.get('question'):
            locator = self.page.locator(self.config['question'])
            actual = locator.inner_text()
            external = locator.get_attribute(self.config['question_id_attribute']) if self.config.get('question_id_attribute') else None
            if normalize(actual) != normalize(snapshot['question']) or (external is not None and external != snapshot['external_id']):
                raise QuestionMismatch(actual, external)

    def submit(self, snapshot, key):
        for field in ('input', 'submit', 'response', 'completion'):
            if not self.config.get(field):
                raise ConnectorError(f'Configure and test the {field} selector first')
        completion = self.page.locator(self.config['completion'])
        if completion.is_visible():
            raise ConnectorError('Completion indicator is already visible; reset the session to prevent stale result capture')
        self.page.locator(self.config['input']).fill(json.loads(snapshot['content'])['candidate_input'])
        self.page.locator(self.config['submit']).click()
        completion.wait_for(state='visible')
        actual = {'output': self.page.locator(self.config['response']).inner_text()}
        for field in ('score', 'feedback'):
            if self.config.get(field):
                value = self.page.locator(self.config[field]).inner_text()
                actual[field] = float(value) if field == 'score' else value
        return actual

    def close(self):
        for attribute in ('context', 'browser'):
            value = getattr(self, attribute, None)
            setattr(self, attribute, None)
            if value:
                try:
                    value.close()
                except Exception:
                    pass
        runtime = getattr(self, 'runtime', None)
        self.runtime = None
        if runtime:
            runtime.stop()


class InterviewConnector(BrowserConnector):
    """Fails closed until the actual site's question matching has been configured."""
    def start_session(self, snapshot):
        if not self.config.get('question'):
            raise ConnectorError('Interview integration needs a verified question locator; live discovery remains blocked until the site is inspected')
        super().start_session(snapshot)


def make_connector(kind, config):
    validate_config(kind, config)
    if kind == 'api' and config.get('adapter') == 'interview_api':
        from .interview_api import InterviewAPIConnector
        return InterviewAPIConnector(config)
    return {'import': ImportedConnector, 'api': APIConnector, 'browser': BrowserConnector, 'interview': InterviewConnector}[kind](config)
