"""Self-declared local identity for attribution, not verified authentication."""
import hashlib
import secrets
import time
from contextvars import ContextVar
from .store import uid, normalize

current_user = ContextVar('evo_user', default=None)
COOKIE = 'evo_session'


def session_user(store, token):
    if not token:
        return None
    rows = store.rows('SELECT u.id,u.name,u.surname FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.deleted_at IS NULL',
                      (hashlib.sha256(token.encode()).hexdigest(), time.time()))
    return rows[0] if rows else None


def clean_identity(name, surname):
    name, surname = ' '.join(str(name).split()), ' '.join(str(surname).split())
    if not name or not surname or len(name) > 80 or len(surname) > 80 or any(ord(c) < 32 for c in name + surname):
        raise ValueError('Enter your name and surname, each up to 80 characters')
    key = normalize(name) + '\n' + normalize(surname)
    return name, surname, key


def sign_in(store, name, surname):
    name, surname, key = clean_identity(name, surname)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT deleted_at FROM users WHERE identity_key=?', (key,)).fetchone()
        if existing and existing['deleted_at']:
            raise ValueError('This user has been removed. Ask a workspace user to restore it in Users.')
        db.execute('INSERT OR IGNORE INTO users(id,name,surname,identity_key) VALUES(?,?,?,?)', (uid(), name, surname, key))
        user = dict(db.execute('SELECT id,name,surname FROM users WHERE identity_key=?', (key,)).fetchone())
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM user_sessions WHERE expires_at<=?', (time.time(),))
        db.execute('INSERT INTO user_sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), user['id'], time.time() + 12 * 3600))
    return token, user


def log_activity(store, user, action, target, status=200):
    store.execute('INSERT INTO activity_log(id,user_id,actor,action,target,status) VALUES(?,?,?,?,?,?)',
                  (uid(), user['id'], user['name'] + ' ' + user['surname'], action, target, status))
