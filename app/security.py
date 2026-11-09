import hashlib
import hmac
import json
import secrets
import time
from functools import wraps
from flask import session, jsonify, request, current_app


def hash_secret(value: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_secret(value: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, expected_hex = encoded.split('$', 2)
        if algorithm != 'scrypt':
            return False
        actual = hashlib.scrypt(value.encode('utf-8'), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def current_actor():
    actor_type = session.get('actor_type')
    actor_id = session.get('actor_id')
    if not actor_type or not actor_id:
        return None
    return {'type': actor_type, 'id': actor_id, 'role': session.get('role'), 'name': session.get('name')}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_actor():
            return jsonify(error='Debes iniciar sesión.'), 401
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            actor = current_actor()
            if actor['role'] not in roles:
                return jsonify(error='No tienes permisos para realizar esta acción.'), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def audit(db, action, entity, entity_id=None, details=None):
    actor = current_actor() or {'type': 'system', 'id': None}
    db.execute(
        'INSERT INTO audit_logs(actor_type, actor_id, action, entity, entity_id, details) VALUES(?,?,?,?,?,?)',
        (actor['type'], actor['id'], action, entity, entity_id, json.dumps(details or {}, ensure_ascii=False))
    )


def rate_limited(db, identity: str, window_seconds=900, max_attempts=5):
    db.execute("DELETE FROM auth_attempts WHERE attempted_at < datetime('now', '-1 day')")
    row = db.execute(
        "SELECT COUNT(*) AS n FROM auth_attempts WHERE identity=? AND success=0 AND attempted_at >= datetime('now', ?) ",
        (identity, f'-{window_seconds} seconds')
    ).fetchone()
    return row['n'] >= max_attempts


def record_attempt(db, identity: str, success: bool):
    db.execute('INSERT INTO auth_attempts(identity, success) VALUES(?,?)', (identity, 1 if success else 0))
