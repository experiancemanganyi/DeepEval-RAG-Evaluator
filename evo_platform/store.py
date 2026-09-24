"""Transactional, versioned SQLite storage. Never migrates or replaces Supabase."""
import csv
import hashlib
import io
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


def uid():
    return str(uuid.uuid4())


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def normalize(value):
    return ' '.join(value.split()).casefold()


def parse_records(text, filename):
    records = list(csv.DictReader(io.StringIO(text))) if filename.lower().endswith('.csv') else json.loads(text)
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError('Import must be an array of records or CSV with column headers.')
    for record in records:
        for key in ('concepts', 'accepted_alternatives', 'expected_concepts', 'score_range', 'turns', 'reference', 'actual', 'rubric'):
            if isinstance(record.get(key), str) and record[key].lstrip().startswith(('[', '{')):
                record[key] = json.loads(record[key])
    return records


class Store:
    def __init__(self, path=None):
        self.path = str(path or os.getenv('EVO_DB_PATH', str(Path(__file__).resolve().parents[1] / 'data' / 'evo.sqlite3')))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY)')
            for migration in sorted(Path(__file__).with_name('migrations').glob('*.sql')):
                if not db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (migration.stem,)).fetchone():
                    # The script and version marker commit together; failed migrations roll back.
                    script = migration.read_text(encoding='utf-8')
                    db.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO schema_migrations VALUES ('" + migration.stem + "');\nCOMMIT;")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, params=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def execute(self, sql, params=()):
        with self.connection() as db:
            return db.execute(sql, params).rowcount

    def save_application(self, name, kind, config):
        from .connectors import validate_config
        validate_config(kind, config)
        with self.connection() as db:
            old = db.execute('SELECT id FROM applications WHERE name=?', (name,)).fetchone()
            app_id = old['id'] if old else uid()
            db.execute('INSERT INTO applications(id,name,kind,config) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,config=excluded.config,deleted_at=NULL', (app_id, name, kind, encode(config)))
        self.record_change('SAVE_APPLICATION', app_id)
        return app_id

    def record_change(self, action, target):
        from .identity import current_user, log_activity
        actor = current_user.get()
        if actor:
            log_activity(self, actor, action, target)

    def import_catalog(self, app_id, records, source='import', verified_totals=None):
        """Deduplicate observations; completeness requires explicit authoritative totals."""
        statistics = {'observations': len(records), 'new_questions': 0, 'duplicates': 0, 'technologies': {}}
        catalog_identities = {}
        with self.connection() as db:
            for record in records:
                technology, text = str(record.get('technology', '')).strip(), str(record.get('question', '')).strip()
                if not technology or not text:
                    raise ValueError('Every record requires technology and question.')
                external_tech = str(record.get('technology_id') or normalize(technology))
                db.execute('INSERT INTO technologies(id,application_id,external_id,name) VALUES(?,?,?,?) ON CONFLICT(application_id,external_id) DO UPDATE SET name=excluded.name,last_sync=CURRENT_TIMESTAMP', (uid(), app_id, external_tech, technology))
                tech_id = db.execute('SELECT id FROM technologies WHERE application_id=? AND external_id=?', (app_id, external_tech)).fetchone()['id']
                external = str(record['question_id']) if record.get('question_id') is not None else None
                identity = 'external:' + external if external is not None else normalize(text) + '|' + str(record.get('difficulty', ''))
                fingerprint = hashlib.sha256(identity.encode()).hexdigest()
                catalog_identities.setdefault(tech_id, set()).add(identity)
                old = db.execute('SELECT * FROM questions WHERE technology_id=? AND (fingerprint=? OR (external_id IS NOT NULL AND external_id=?))', (tech_id, fingerprint, external)).fetchone()
                if old:
                    if normalize(old['text']) != normalize(text):
                        raise ValueError('Question ID was reused with changed text; review and version the catalog before import.')
                    db.execute('UPDATE questions SET observations=observations+1 WHERE id=?', (old['id'],))
                    statistics['duplicates'] += 1
                else:
                    question_id = uid()
                    db.execute('INSERT INTO questions(id,technology_id,external_id,fingerprint,text,difficulty,source) VALUES(?,?,?,?,?,?,?)', (question_id, tech_id, external, fingerprint, text, record.get('difficulty'), source))
                    reference = {key: record[key] for key in ('expected_answer', 'concepts', 'accepted_alternatives', 'rubric', 'max_score', 'rubric_version') if key in record}
                    reference.update(question=text, technology=technology, external_question_id=external)
                    db.execute('INSERT INTO chunks(id,question_id,kind,content,source,version) VALUES(?,?,?,?,?,1)', (uid(), question_id, 'structured', encode(reference), source))
                    statistics['new_questions'] += 1
            for tech in db.execute('SELECT * FROM technologies WHERE application_id=?', (app_id,)):
                counts = db.execute('SELECT COUNT(*) n,SUM(observations) observations FROM questions WHERE technology_id=?', (tech['id'],)).fetchone()
                total = (verified_totals or {}).get(tech['external_id'])
                collected = len(catalog_identities.get(tech['id'], set()))
                statistics['technologies'][tech['name']] = {'unique_questions': counts['n'], 'collected_this_sync': collected, 'duplicate_observations': (counts['observations'] or 0) - counts['n'], 'authoritative_total': total, 'complete': total is not None and counts['n'] == total and collected == total, 'unretrieved': max(0, total - collected) if total is not None else None}
            db.execute('INSERT INTO discoveries(id,application_id,statistics) VALUES(?,?,?)', (uid(), app_id, encode(statistics)))
        return statistics

    def import_technologies(self, app_id, technologies):
        with self.connection() as db:
            for technology in technologies:
                name = str(technology['name']).strip()
                if not name:
                    continue
                external = str(technology.get('id') or normalize(name))
                db.execute('INSERT INTO technologies(id,application_id,external_id,name) VALUES(?,?,?,?) ON CONFLICT(application_id,external_id) DO UPDATE SET name=excluded.name,last_sync=CURRENT_TIMESTAMP', (uid(), app_id, external, name))

    def questions(self, app_id):
        return self.rows('SELECT q.*, t.name technology,t.external_id technology_external_id FROM questions q JOIN technologies t ON q.technology_id=t.id WHERE t.application_id=? ORDER BY t.name,q.text', (app_id,))

    def reference(self, question_id):
        rows = self.rows('SELECT * FROM chunks WHERE question_id=? AND active=1 ORDER BY version DESC LIMIT 1', (question_id,))
        return rows[0] if rows else None

    def revise_chunk(self, chunk_id, content, validation='unverified', require_current=False):
        if not isinstance(content, dict):
            raise ValueError('Chunk content must be a JSON object')
        if validation not in ('unverified', 'approved', 'generated'):
            raise ValueError('Invalid validation status')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM chunks WHERE id=?', (chunk_id,)).fetchone()
            if not old:
                raise ValueError('Unknown chunk')
            column, parent = ('question_id', old['question_id']) if old['question_id'] else ('document_id', old['document_id'])
            if require_current:
                current = db.execute(f'SELECT id FROM chunks WHERE {column}=? AND active=1 ORDER BY version DESC LIMIT 1', (parent,)).fetchone()
                if not current or current['id'] != chunk_id:
                    raise ValueError('Reference changed during generation; refresh and review its latest version')
            version = db.execute(f'SELECT MAX(version) v FROM chunks WHERE {column}=?', (parent,)).fetchone()['v'] + 1
            new_id = uid()
            db.execute('INSERT INTO chunks(id,question_id,document_id,kind,content,source,version,validation) VALUES(?,?,?,?,?,?,?,?)', (new_id, old['question_id'], old['document_id'], old['kind'], encode(content), 'llm-generated' if validation == 'generated' else old['source'], version, validation))
            return new_id

    def approve_references(self, app_id, chunk_ids):
        ids = list(dict.fromkeys(chunk_ids))
        if not ids or len(ids) > 200:
            raise ValueError('Select between 1 and 200 references')
        created = []
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for chunk_id in ids:
                row = db.execute('SELECT c.* FROM chunks c JOIN questions q ON q.id=c.question_id JOIN technologies t ON t.id=q.technology_id WHERE c.id=? AND t.application_id=? AND c.active=1', (chunk_id, app_id)).fetchone()
                if not row:
                    raise ValueError('Selected reference is unavailable or belongs to another application')
                latest = db.execute('SELECT id FROM chunks WHERE question_id=? AND active=1 ORDER BY version DESC LIMIT 1', (row['question_id'],)).fetchone()
                if latest['id'] != chunk_id:
                    raise ValueError('A selected reference changed. Refresh and review the latest versions before approving')
                content = json.loads(row['content'])
                if not any(content.get(k) for k in ('expected_answer', 'concepts', 'rubric')):
                    raise ValueError('Generate proposals or enter reference content before approving')
                if row['validation'] == 'approved':
                    continue
                new_id = uid()
                version = db.execute('SELECT MAX(version) v FROM chunks WHERE question_id=?', (row['question_id'],)).fetchone()['v'] + 1
                db.execute("INSERT INTO chunks(id,question_id,kind,content,source,version,validation) VALUES(?,?,'structured',?,?,?,'approved')", (new_id, row['question_id'], row['content'], row['source'], version))
                created.append(new_id)
        for new_id in created:
            self.record_change('APPROVE_REFERENCE', new_id)
        return created

    def save_document_chunk(self, text, metadata, source='existing-rag'):
        document_id = str(metadata.get('file_id') or metadata.get('file_title') or 'unknown')
        content = encode({'text': text, 'metadata': metadata})
        digest = hashlib.sha256((document_id + content).encode()).hexdigest()
        self.execute('INSERT OR IGNORE INTO chunks(id,document_id,kind,content,source,version) VALUES(?,?,?,?,?,1)', (digest, document_id, 'document', content, source))

    def create_dataset(self, app_id, name, cases, source='import'):
        dataset_id = uid()
        with self.connection() as db:
            db.execute('INSERT INTO datasets(id,name,application_id,source) VALUES(?,?,?,?)', (dataset_id, name, app_id, source))
            for case in cases:
                question_id = case['question_id']
                if not db.execute('SELECT 1 FROM questions q JOIN technologies t ON t.id=q.technology_id WHERE q.id=? AND t.application_id=?', (question_id, app_id)).fetchone():
                    raise ValueError('Question does not belong to this application')
                if not isinstance(case.get('candidate_input'), str):
                    raise ValueError('candidate_input must be text (empty is allowed)')
                ref = db.execute('SELECT id FROM chunks WHERE question_id=? AND active=1 ORDER BY version DESC LIMIT 1', (question_id,)).fetchone()
                db.execute('INSERT INTO cases(id,dataset_id,question_id,chunk_id,content) VALUES(?,?,?,?,?)', (uid(), dataset_id, question_id, ref['id'] if ref else None, encode(case)))
        self.record_change('CREATE_DATASET', dataset_id)
        return dataset_id

    def create_run(self, app_id, case_ids, config):
        if not case_ids:
            raise ValueError('Select at least one test case')
        from .identity import current_user
        actor = current_user.get()
        config = dict(config, initiated_by=actor)
        run_id = uid()
        with self.connection() as db:
            app = db.execute('SELECT * FROM applications WHERE id=? AND deleted_at IS NULL', (app_id,)).fetchone()
            if not app:
                raise ValueError('Application is no longer active')
            config = dict(config, application=dict(app))
            db.execute('INSERT INTO runs(id,application_id,config) VALUES(?,?,?)', (run_id, app_id, encode(config)))
            for case_id in dict.fromkeys(case_ids):
                row = db.execute('SELECT c.*,q.text question,q.external_id,q.technology_id,t.name technology,t.external_id technology_external_id,d.application_id FROM cases c JOIN questions q ON q.id=c.question_id JOIN technologies t ON t.id=q.technology_id JOIN datasets d ON d.id=c.dataset_id WHERE c.id=? AND d.deleted_at IS NULL', (case_id,)).fetchone()
                if not row or row['application_id'] != app_id:
                    raise ValueError('Case belongs to another application')
                snap = dict(row)
                ref = db.execute('SELECT * FROM chunks WHERE id=?', (row['chunk_id'],)).fetchone()
                snap['reference'] = dict(ref) if ref else None
                db.execute('INSERT INTO results(id,run_id,case_id,snapshot) VALUES(?,?,?,?)', (uid(), run_id, case_id, encode(snap)))
        self.record_change('CREATE_RUN', run_id)
        return run_id

    def results(self, run_id):
        return self.rows('SELECT * FROM results WHERE run_id=? ORDER BY rowid', (run_id,))

    def export_results(self, run_id, format='json'):
        rows = self.results(run_id)
        if format == 'json':
            return encode(rows)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['id'])
        writer.writeheader()
        # Avoid spreadsheet formula execution in exported untrusted text.
        writer.writerows({k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v) for k, v in row.items()} for row in rows)
        return stream.getvalue()
