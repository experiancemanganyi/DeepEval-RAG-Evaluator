CREATE TABLE IF NOT EXISTS cloud_sync (
 run_id TEXT PRIMARY KEY REFERENCES runs(id),
 state TEXT NOT NULL DEFAULT 'pending',
 dataset_alias TEXT,
 dataset_uploaded INTEGER NOT NULL DEFAULT 0,
 confident_link TEXT,
 message TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
