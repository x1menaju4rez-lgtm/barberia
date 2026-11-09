import sqlite3
from pathlib import Path
from flask import g, current_app


def get_db():
    if 'db' not in g:
        db_path = current_app.config['DATABASE']
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA journal_mode = WAL')
        connection.execute('PRAGMA busy_timeout = 15000')
        g.db = connection
    return g.db


def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    schema = Path(app.root_path, 'schema.sql').read_text(encoding='utf-8')
    db_path = Path(app.config['DATABASE'])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(schema)
    connection.commit()
    connection.close()


def get_client_by_phone(db, phone):
    return db.execute('SELECT * FROM clients WHERE phone=? AND active=1', (phone,)).fetchone()
