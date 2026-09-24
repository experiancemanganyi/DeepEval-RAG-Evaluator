CREATE TABLE IF NOT EXISTS applications (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, config TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS technologies (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 external_id TEXT NOT NULL, name TEXT NOT NULL, last_sync TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(application_id, external_id));
CREATE TABLE IF NOT EXISTS questions (
 id TEXT PRIMARY KEY, technology_id TEXT NOT NULL REFERENCES technologies(id),
 external_id TEXT, fingerprint TEXT NOT NULL, text TEXT NOT NULL, difficulty TEXT,
 observations INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL,
 UNIQUE(technology_id, fingerprint));
CREATE UNIQUE INDEX IF NOT EXISTS question_external ON questions(technology_id, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, question_id TEXT REFERENCES questions(id), document_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('document','structured')), content TEXT NOT NULL,
 source TEXT NOT NULL, version INTEGER NOT NULL, validation TEXT NOT NULL DEFAULT 'unverified',
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK((question_id IS NOT NULL AND document_id IS NULL) OR (question_id IS NULL AND document_id IS NOT NULL)));
CREATE INDEX IF NOT EXISTS chunk_question ON chunks(question_id,version);
CREATE INDEX IF NOT EXISTS chunk_document ON chunks(document_id,version);
CREATE TABLE IF NOT EXISTS datasets (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, application_id TEXT NOT NULL REFERENCES applications(id),
 source TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cases (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
 question_id TEXT NOT NULL REFERENCES questions(id), chunk_id TEXT REFERENCES chunks(id),
 content TEXT NOT NULL, validation TEXT NOT NULL DEFAULT 'unverified');
CREATE INDEX IF NOT EXISTS case_dataset ON cases(dataset_id);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 config TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS results (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), case_id TEXT NOT NULL REFERENCES cases(id),
 snapshot TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', actual TEXT,
 metrics TEXT, error TEXT, duration REAL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(run_id,case_id));
CREATE INDEX IF NOT EXISTS result_run ON results(run_id,state);
CREATE TABLE IF NOT EXISTS discoveries (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id), statistics TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
