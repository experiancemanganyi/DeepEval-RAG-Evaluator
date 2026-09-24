"""Synthetic local servers: these tests do not prove real interview integration."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from evo_platform.connectors import BrowserConnector, APIConnector, ConnectorError


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        submissions = 0
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            if self.path.startswith('/catalog'):
                self.wfile.write(json.dumps({'questions': [{'technology': 'T', 'question': 'Q', 'question_id': '1'}], 'totals': {'t': 1}}).encode())
            else:
                self.wfile.write(b'''<html><body><h1 id="question">Q</h1><textarea id="answer"></textarea><button id="submit" onclick="document.querySelector('#output').textContent='Feedback';document.querySelector('#score').textContent='8';document.querySelector('#done').hidden=false">Submit</button><div id="output"></div><span id="score"></span><span id="done" hidden>Complete</span></body></html>''')
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            Handler.submissions += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'output': 'Feedback', 'score': 8, 'question_id': data['question_id']}).encode())
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{http.server_port}', Handler
    http.shutdown()
    http.server_close()
    worker.join()


def snapshot():
    return {'external_id': '1', 'question': 'Q', 'technology_external_id': 't', 'content': json.dumps({'candidate_input': 'Answer'})}


def test_local_api_round_trip(server):
    url, handler = server
    connector = APIConnector({'url': url, 'catalog_path': 'catalog', 'submit_path': 'submit'})
    connector.connect()
    try:
        records, totals = connector.catalog()
        assert records[0]['question'] == 'Q' and totals == {'t': 1}
        assert connector.submit(snapshot(), 'unique-key')['score'] == 8
        assert handler.submissions == 1
    finally:
        connector.close()


def test_missing_auth_variable(monkeypatch):
    monkeypatch.delenv('EVO_MISSING_TEST_TOKEN', raising=False)
    connector = APIConnector({'url': 'https://example.com', 'token_env': 'EVO_MISSING_TEST_TOKEN'})
    with pytest.raises(ConnectorError):
        connector.connect()
    connector.close()


@pytest.mark.browser
def test_browser_round_trip_and_question_guard(server):
    pytest.importorskip('playwright')
    url, _ = server
    connector = BrowserConnector({'url': url, 'browser_channel': 'msedge' if os.name == 'nt' else '', 'question': '#question', 'input': '#answer', 'submit': '#submit', 'response': '#output', 'score': '#score', 'completion': '#done', 'timeout': 5})
    connector.connect()
    try:
        assert connector.diagnostics()['input']['matches'] == 1
        wrong = dict(snapshot(), question='Different question')
        with pytest.raises(ConnectorError):
            connector.start_session(wrong)
        connector.start_session(snapshot())
        actual = connector.submit(snapshot(), 'key')
        assert actual == {'output': 'Feedback', 'score': 8.0}
        with pytest.raises(ConnectorError):
            connector.submit(snapshot(), 'key2')
    finally:
        connector.close()


def test_tls_exception_is_per_origin(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {}
    observed = []
    connector = APIConnector({'url': 'https://example.com', 'certificate_exception_origin': 'https://example.com'})
    connector.connect()
    monkeypatch.setattr(connector.session, 'request', lambda *args, **kwargs: observed.append(kwargs) or Response())
    connector.request('GET', '/catalog')
    assert observed[0]['verify'] is False
    with pytest.raises(ConnectorError):
        connector.request('GET', 'https://elsewhere.com')
    assert len(observed) == 1
    connector.close()
