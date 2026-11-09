import tempfile
import unittest
from werkzeug.security import generate_password_hash
from pathlib import Path
from app import create_app


class LegendaryBarberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({
            'TESTING': True,
            'DATABASE': db_path,
            'SECRET_KEY': 'test-secret-key',
            'DEV_SHOW_OTP': False,
            'ADMIN_PASSWORD_HASH': generate_password_hash('AdminTest!2026'),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'ok')

    def test_seeded_services_and_staff(self):
        with self.app.app_context():
            from app.db import get_db
            db = get_db()
            self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM employees').fetchone()['n'], 16)
            self.assertGreater(db.execute('SELECT COUNT(*) AS n FROM services').fetchone()['n'], 20)
            self.assertGreater(db.execute('SELECT COUNT(*) AS n FROM products').fetchone()['n'], 20)

    def test_admin_login_requires_password(self):
        response = self.client.post('/api/auth/staff', json={'code':'2541500260','admin_password':'wrong'})
        self.assertEqual(response.status_code, 401)

    def test_customer_phone_validation(self):
        response = self.client.post('/api/auth/request-otp', json={'full_name':'Juan Pérez','phone':'123'})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
