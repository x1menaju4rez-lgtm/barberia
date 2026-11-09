import os
import secrets
from pathlib import Path
from datetime import timedelta
from flask import Flask, jsonify, send_from_directory
from werkzeug.security import generate_password_hash
from .db import init_db, close_db, get_db
from .seed import seed_database
from .routes import api


def create_app(test_config=None):
    app = Flask(__name__, static_folder='../static', static_url_path='/static')
    base_dir = Path(__file__).resolve().parent.parent
    database_setting = Path(os.getenv('DATABASE_PATH', 'instance/legendary_barber.sqlite3'))
    database_path = database_setting if database_setting.is_absolute() else base_dir / database_setting
    debug_mode = os.getenv('FLASK_DEBUG', '1') == '1'
    configured_secret = os.getenv('SECRET_KEY', '')
    admin_password = os.getenv('LEGENDARY_ADMIN_PASSWORD', '')
    if not debug_mode and (len(configured_secret) < 32 or len(admin_password) < 12 or admin_password.startswith('CAMBIAR')):
        raise RuntimeError('Configura SECRET_KEY y LEGENDARY_ADMIN_PASSWORD seguros antes de ejecutar en producción.')
    app.config.update(
        SECRET_KEY=configured_secret or secrets.token_urlsafe(48),
        DATABASE=str(database_path),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=10),
        DEBUG=debug_mode,
        DEV_SHOW_OTP=os.getenv('DEV_SHOW_OTP', '1') == '1',
        SMS_PROVIDER_CONFIGURED=os.getenv('SMS_PROVIDER_CONFIGURED', '0') == '1',
        ADMIN_PASSWORD_HASH=generate_password_hash(admin_password or 'CAMBIAR-ADMIN-PASSWORD'),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    init_db(app)
    app.teardown_appcontext(close_db)
    with app.app_context():
        seed_database(get_db())
    app.register_blueprint(api, url_prefix='/api')

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/manifest.json')
    def manifest():
        return send_from_directory(app.static_folder, 'manifest.json')

    @app.get('/service-worker.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'service-worker.js')
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', database='sqlite', app='Legendary Barber')

    return app
