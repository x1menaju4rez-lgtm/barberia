import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash
from .db import get_db, get_client_by_phone
from .security import hash_secret, verify_secret, current_actor, login_required, roles_required, audit, rate_limited, record_attempt

api = Blueprint('api', __name__)
PHONE_RE = re.compile(r'^\d{10}$')
NAME_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñÀ-ÿ][A-Za-zÁÉÍÓÚÜÑáéíóúüñÀ-ÿ .'-]{1,99}$")
ACTIVE_APPOINTMENT_STATES = ('pendiente', 'aceptada', 'reasignada')


def payload():
    return request.get_json(silent=True) or {}


def money(value):
    try:
        number = round(float(value), 2)
        if number < 0:
            raise ValueError
        return int(round(number * 100))
    except (TypeError, ValueError):
        raise ValueError('El precio debe ser un número igual o mayor que cero.')


def serialize(row):
    return dict(row) if row is not None else None


def actor_id_for_employee():
    actor = current_actor()
    return actor['id'] if actor and actor['type'] == 'employee' else None


def valid_appointment_slot(db, barber_id, starts_at, ends_at, ignore_id=None):
    if not barber_id:
        return True
    query = "SELECT id FROM appointments WHERE barber_id=? AND status IN ('pendiente','aceptada','reasignada') AND starts_at < ? AND ends_at > ?"
    params = [barber_id, ends_at, starts_at]
    if ignore_id:
        query += ' AND id<>?'
        params.append(ignore_id)
    return db.execute(query, params).fetchone() is None


def as_iso(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (AttributeError, ValueError):
        raise ValueError('Fecha inválida. Usa ISO 8601, por ejemplo 2026-11-12T15:00:00-06:00.')


def ensure_csrf():
    token = session.get('csrf_token')
    supplied = request.headers.get('X-CSRF-Token')
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and current_actor() and supplied != token:
        return jsonify(error='Token de seguridad inválido. Recarga la página.'), 403
    return None


@api.before_request
def csrf_guard():
    if request.endpoint not in ('api.request_otp', 'api.verify_otp', 'api.customer_register', 'api.staff_login', 'api.logout'):
        return ensure_csrf()


@api.get('/me')
def me():
    actor = current_actor()
    if not actor:
        return jsonify(authenticated=False)
    session.setdefault('csrf_token', secrets.token_urlsafe(24))
    actor['csrf_token'] = session['csrf_token']
    if actor['type'] == 'customer':
        row = get_db().execute('SELECT id,full_name,phone FROM clients WHERE id=?', (actor['id'],)).fetchone()
        actor['client'] = serialize(row)
    return jsonify(authenticated=True, user=actor)


@api.post('/auth/request-otp')
def request_otp():
    data = payload()
    phone = str(data.get('phone', '')).strip()
    full_name = str(data.get('full_name', '')).strip()
    if not PHONE_RE.fullmatch(phone):
        return jsonify(error='El teléfono debe contener exactamente 10 dígitos.'), 400
    db = get_db()
    existing = get_client_by_phone(db, phone)
    if full_name:
        if not NAME_RE.fullmatch(full_name) or any(ch.isdigit() for ch in full_name):
            return jsonify(error='Escribe un nombre completo válido, sin números ni símbolos no permitidos.'), 400
        if existing:
            return jsonify(error='Este teléfono ya está registrado. Inicia sesión o recupera tu acceso'), 409
    elif not existing:
        return jsonify(error='No encontramos una cuenta con ese teléfono. Regístrate primero.'), 404
    if rate_limited(db, f'otp:{phone}', max_attempts=5):
        return jsonify(error='Demasiados intentos. Intenta de nuevo más tarde.'), 429
    otp = f'{secrets.randbelow(1_000_000):06d}'
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db.execute('UPDATE otp_codes SET consumed=1 WHERE phone=? AND consumed=0', (phone,))
    db.execute('INSERT INTO otp_codes(phone,full_name,code_hash,expires_at) VALUES(?,?,?,?)',
               (phone, full_name or None, hash_secret(otp), expires))
    record_attempt(db, f'otp:{phone}', False)
    db.commit()
    if current_app.config['DEV_SHOW_OTP'] and not current_app.config['SMS_PROVIDER_CONFIGURED']:
        print(f'\n[LEGENDARY BARBER - OTP DE DESARROLLO] Teléfono {phone}: {otp} (vence en 5 minutos)\n', flush=True)
    response = {'message': 'Código solicitado. En desarrollo, revisa la terminal del servidor.'}
    if current_app.config['DEV_SHOW_OTP'] and not current_app.config['SMS_PROVIDER_CONFIGURED']:
        response['development_notice'] = 'El código aparece en la terminal donde ejecutaste run.py; no se envía un SMS real.'
    return jsonify(response)


@api.post('/auth/verify-otp')
def verify_otp():
    data = payload()
    phone = str(data.get('phone', '')).strip()
    otp = str(data.get('otp', '')).strip()
    if not PHONE_RE.fullmatch(phone) or not re.fullmatch(r'\d{6}', otp):
        return jsonify(error='Teléfono o código inválido.'), 400
    db = get_db()
    if rate_limited(db, f'verify:{phone}', max_attempts=5):
        return jsonify(error='Demasiados intentos. Intenta más tarde.'), 429
    row = db.execute('SELECT * FROM otp_codes WHERE phone=? AND consumed=0 ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
    valid = False
    if row:
        try:
            valid = datetime.fromisoformat(row['expires_at']) > datetime.now(timezone.utc) and verify_secret(otp, row['code_hash'])
        except ValueError:
            valid = False
    record_attempt(db, f'verify:{phone}', valid)
    if not valid:
        db.commit()
        return jsonify(error='Código incorrecto o vencido.'), 401
    db.execute('UPDATE otp_codes SET consumed=1 WHERE id=?', (row['id'],))
    client = get_client_by_phone(db, phone)
    if not client:
        if not row['full_name']:
            db.commit()
            return jsonify(error='No existe la cuenta. Regístrate primero.'), 404
        db.execute('INSERT INTO clients(full_name,phone) VALUES(?,?)', (row['full_name'], phone))
        client = get_client_by_phone(db, phone)
        audit(db, 'registro_cliente', 'client', client['id'], {'phone': phone})
    session.clear()
    session.permanent = True
    session['actor_type'] = 'customer'
    session['actor_id'] = client['id']
    session['role'] = 'customer'
    session['name'] = client['full_name']
    session['csrf_token'] = secrets.token_urlsafe(24)
    db.commit()
    return jsonify(message='Sesión iniciada.', user={'id': client['id'], 'name': client['full_name'], 'phone': phone, 'role': 'customer'}, csrf_token=session['csrf_token'])


@api.post('/auth/staff')
def staff_login():
    data = payload()
    code = str(data.get('code', '')).strip()
    admin_password = str(data.get('admin_password', ''))
    if not re.fullmatch(r'\d{10}', code):
        return jsonify(error='El código debe contener 10 dígitos.'), 400
    db = get_db()
    if rate_limited(db, f'staff:{code}', max_attempts=5):
        return jsonify(error='Acceso bloqueado temporalmente por demasiados intentos.'), 429
    employee = None
    for candidate in db.execute('SELECT * FROM employees WHERE active=1'):
        if verify_secret(code, candidate['code_hash']):
            employee = candidate
            break
    valid = bool(employee)
    if employee and employee['role'] == 'admin':
        valid = bool(admin_password) and check_password_hash(current_app.config['ADMIN_PASSWORD_HASH'], admin_password)
    record_attempt(db, f'staff:{code}', valid)
    if not valid:
        db.commit()
        return jsonify(error='Código o contraseña incorrectos.'), 401
    session.clear()
    session.permanent = True
    session['actor_type'] = 'employee'
    session['actor_id'] = employee['id']
    session['role'] = employee['role']
    session['name'] = employee['full_name']
    session['csrf_token'] = secrets.token_urlsafe(24)
    audit(db, 'inicio_sesion', 'employee', employee['id'], {'role': employee['role']})
    db.commit()
    return jsonify(message='Acceso correcto.', user={'id': employee['id'], 'name': employee['full_name'], 'role': employee['role']}, csrf_token=session['csrf_token'])


@api.post('/logout')
def logout():
    session.clear()
    return jsonify(message='Sesión cerrada.')


@api.get('/services')
def list_services():
    db = get_db()
    actor = current_actor()
    if actor and actor['role'] == 'admin':
        rows = db.execute('SELECT * FROM services ORDER BY category,name').fetchall()
    else:
        rows = db.execute('SELECT * FROM services WHERE active=1 AND published=1 ORDER BY category,name').fetchall()
    return jsonify(items=[serialize(row) for row in rows])


@api.post('/services')
@roles_required('admin')
def create_service():
    data, db = payload(), get_db()
    try:
        name = str(data.get('name', '')).strip()
        category = str(data.get('category', '')).strip()
        price = money(data.get('price', 0))
        duration = int(data.get('duration_minutes', 30))
        if not name or not category or duration < 1 or duration > 600:
            raise ValueError('Nombre, categoría y duración válida son obligatorios.')
        cur = db.execute('INSERT INTO services(category,name,description,price_cents,duration_minutes,active,published) VALUES(?,?,?,?,?,?,?)',
                         (category, name, str(data.get('description', '')).strip(), price, duration, 1, int(bool(data.get('published', False)))))
        audit(db, 'crear', 'service', cur.lastrowid, {'name': name})
        db.commit()
        return jsonify(id=cur.lastrowid, message='Servicio creado.'), 201
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@api.put('/services/<int:item_id>')
@roles_required('admin')
def update_service(item_id):
    data, db = payload(), get_db()
    row = db.execute('SELECT * FROM services WHERE id=?', (item_id,)).fetchone()
    if not row:
        return jsonify(error='Servicio no encontrado.'), 404
    try:
        price = money(data.get('price', row['price_cents'] / 100))
        duration = int(data.get('duration_minutes', row['duration_minutes']))
        if duration < 1 or duration > 600:
            raise ValueError('Duración inválida.')
        db.execute('UPDATE services SET category=?,name=?,description=?,price_cents=?,duration_minutes=?,active=?,published=? WHERE id=?',
                   (str(data.get('category', row['category'])).strip(), str(data.get('name', row['name'])).strip(),
                    str(data.get('description', row['description'])).strip(), price, duration,
                    int(bool(data.get('active', row['active']))), int(bool(data.get('published', row['published']))), item_id))
        audit(db, 'actualizar', 'service', item_id)
        db.commit()
        return jsonify(message='Servicio actualizado.')
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@api.get('/products')
def list_products():
    db = get_db()
    actor = current_actor()
    if actor and actor['role'] in ('admin', 'inventory', 'cashier'):
        rows = db.execute('SELECT * FROM products WHERE active=1 ORDER BY name').fetchall()
    elif actor and actor['role'] == 'specialist':
        rows = db.execute('SELECT id,name,stock,min_stock FROM products WHERE active=1 ORDER BY name').fetchall()
    else:
        rows = db.execute('SELECT id,name,description,price_cents FROM products WHERE active=1 AND published=1 ORDER BY name').fetchall()
    return jsonify(items=[serialize(row) for row in rows])


@api.post('/products')
@roles_required('admin')
def create_product():
    data, db = payload(), get_db()
    try:
        name = str(data.get('name', '')).strip()
        if not name:
            raise ValueError('El nombre del producto es obligatorio.')
        price, cost = money(data.get('price', 0)), money(data.get('cost', 0))
        stock, minimum = int(data.get('stock', 0)), int(data.get('min_stock', 0))
        if min(stock, minimum) < 0:
            raise ValueError('Las existencias no pueden ser negativas.')
        cur = db.execute('INSERT INTO products(name,description,brand,price_cents,cost_cents,stock,min_stock,supplier,published) VALUES(?,?,?,?,?,?,?,?,?)',
                         (name, str(data.get('description', '')).strip(), str(data.get('brand', '')).strip(), price, cost,
                          stock, minimum, str(data.get('supplier', '')).strip(), int(bool(data.get('published', False)))))
        if stock:
            db.execute('INSERT INTO inventory_movements(product_id,movement_type,quantity,reason,status,requested_by,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                       (cur.lastrowid, 'entrada', stock, 'Existencia inicial', 'aprobado', actor_id_for_employee(), actor_id_for_employee()))
        audit(db, 'crear', 'product', cur.lastrowid, {'name': name})
        db.commit()
        return jsonify(id=cur.lastrowid, message='Producto creado.'), 201
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@api.put('/products/<int:item_id>')
@roles_required('admin')
def update_product(item_id):
    data, db = payload(), get_db()
    row = db.execute('SELECT * FROM products WHERE id=?', (item_id,)).fetchone()
    if not row:
        return jsonify(error='Producto no encontrado.'), 404
    try:
        price = money(data.get('price', row['price_cents'] / 100))
        cost = money(data.get('cost', row['cost_cents'] / 100))
        db.execute('UPDATE products SET name=?,description=?,brand=?,price_cents=?,cost_cents=?,min_stock=?,supplier=?,active=?,published=? WHERE id=?',
                   (str(data.get('name', row['name'])).strip(), str(data.get('description', row['description'])).strip(),
                    str(data.get('brand', row['brand'])).strip(), price, cost, int(data.get('min_stock', row['min_stock'])),
                    str(data.get('supplier', row['supplier'])).strip(), int(bool(data.get('active', row['active']))),
                    int(bool(data.get('published', row['published']))), item_id))
        audit(db, 'actualizar', 'product', item_id)
        db.commit()
        return jsonify(message='Producto actualizado.')
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@api.get('/employees')
@roles_required('admin')
def list_employees():
    rows = get_db().execute('SELECT id,full_name,role,active,created_at FROM employees ORDER BY role,full_name').fetchall()
    return jsonify(items=[serialize(row) for row in rows])


@api.get('/appointments')
@login_required
def list_appointments():
    db, actor = get_db(), current_actor()
    query = '''SELECT a.*, c.full_name AS client_name, c.phone AS client_phone, e.full_name AS barber_name
               FROM appointments a JOIN clients c ON c.id=a.client_id
               LEFT JOIN employees e ON e.id=a.barber_id'''
    params = []
    if actor['type'] == 'customer':
        query += ' WHERE a.client_id=?'
        params.append(actor['id'])
    elif actor['role'] == 'barber':
        query += ' WHERE a.barber_id=?'
        params.append(actor['id'])
    elif actor['role'] == 'specialist':
        query += " WHERE a.status IN ('pendiente','aceptada','reasignada','completada')"
    query += ' ORDER BY a.starts_at DESC LIMIT 250'
    rows = db.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = serialize(row)
        item['services'] = [serialize(s) for s in db.execute('SELECT service_id,service_name,price_cents,duration_minutes FROM appointment_services WHERE appointment_id=?', (row['id'],)).fetchall()]
        result.append(item)
    return jsonify(items=result)


@api.post('/appointments')
@roles_required('admin')
def create_appointment():
    data, db = payload(), get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        client_id = int(data.get('client_id'))
        barber_id = int(data.get('barber_id')) if data.get('barber_id') else None
        start = as_iso(data.get('starts_at'))
        service_ids = data.get('service_ids') or []
        if not isinstance(service_ids, list) or not 1 <= len(service_ids) <= 3:
            raise ValueError('Selecciona entre uno y tres servicios.')
        if start <= datetime.now(timezone.utc) - timedelta(minutes=1):
            raise ValueError('La cita debe programarse en el futuro.')
        placeholders = ','.join('?' for _ in service_ids)
        services = db.execute(f'SELECT * FROM services WHERE id IN ({placeholders}) AND active=1', tuple(service_ids)).fetchall()
        if len(services) != len(set(service_ids)):
            raise ValueError('Uno o más servicios no existen o están inactivos.')
        total_minutes = sum(s['duration_minutes'] for s in services)
        end = start + timedelta(minutes=total_minutes)
        start_text, end_text = start.isoformat(), end.isoformat()
        if barber_id and not db.execute("SELECT id FROM employees WHERE id=? AND role='barber' AND active=1", (barber_id,)).fetchone():
            raise ValueError('El barbero seleccionado no es válido.')
        if not valid_appointment_slot(db, barber_id, start_text, end_text):
            raise ValueError('El barbero ya tiene una cita en ese horario.')
        cur = db.execute('INSERT INTO appointments(client_id,barber_id,starts_at,ends_at,status,notes,created_by) VALUES(?,?,?,?,?,?,?)',
                         (client_id, barber_id, start_text, end_text, 'pendiente', str(data.get('notes', '')).strip(), actor_id_for_employee()))
        for service in services:
            db.execute('INSERT INTO appointment_services(appointment_id,service_id,service_name,price_cents,duration_minutes) VALUES(?,?,?,?,?)',
                       (cur.lastrowid, service['id'], service['name'], service['price_cents'], service['duration_minutes']))
        audit(db, 'crear_cita', 'appointment', cur.lastrowid, {'barber_id': barber_id, 'service_ids': service_ids})
        db.commit()
        return jsonify(id=cur.lastrowid, status='pendiente', message='Solicitud registrada.'), 201
    except (ValueError, TypeError, OverflowError) as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400


@api.patch('/appointments/<int:appointment_id>/decision')
@roles_required('barber', 'admin')
def appointment_decision(appointment_id):
    data, db, actor = payload(), get_db(), current_actor()
    decision = data.get('decision')
    if decision not in ('aceptada', 'rechazada'):
        return jsonify(error='Decisión inválida.'), 400
    row = db.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,)).fetchone()
    if not row:
        return jsonify(error='Cita no encontrada.'), 404
    if actor['role'] == 'barber' and row['barber_id'] != actor['id']:
        return jsonify(error='Esta cita no está asignada a tu agenda.'), 403
    db.execute('UPDATE appointments SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (decision, appointment_id))
    audit(db, decision, 'appointment', appointment_id)
    db.commit()
    return jsonify(message=f'Cita {decision}.')


@api.patch('/appointments/<int:appointment_id>/cancel')
@login_required
def cancel_appointment(appointment_id):
    db, actor = get_db(), current_actor()
    row = db.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,)).fetchone()
    if not row:
        return jsonify(error='Cita no encontrada.'), 404
    if actor['type'] == 'customer' and row['client_id'] != actor['id']:
        return jsonify(error='No puedes cancelar una cita que no te pertenece.'), 403
    if actor['type'] == 'employee' and actor['role'] != 'admin' and not (actor['role'] == 'barber' and row['barber_id'] == actor['id']):
        return jsonify(error='No tienes permisos para cancelar esta cita.'), 403
    if row['status'] in ('cancelada', 'completada'):
        return jsonify(error='Esta cita ya no puede cancelarse.'), 409
    db.execute("UPDATE appointments SET status='cancelada',cancelled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?", (appointment_id,))
    audit(db, 'cancelar_cita', 'appointment', appointment_id, {'reason': str(payload().get('reason', 'Cancelación solicitada'))})
    db.commit()
    return jsonify(message='Cita cancelada; el horario quedó liberado.')


@api.patch('/appointments/<int:appointment_id>/complete')
@roles_required('barber', 'admin', 'specialist')
def complete_appointment(appointment_id):
    db, actor = get_db(), current_actor()
    db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,)).fetchone()
    if not row:
        db.rollback()
        return jsonify(error='Cita no encontrada.'), 404
    if actor['role'] == 'barber' and row['barber_id'] != actor['id']:
        db.rollback()
        return jsonify(error='No puedes completar una cita ajena.'), 403
    if row['status'] not in ('aceptada', 'reasignada'):
        db.rollback()
        return jsonify(error='Solo pueden completarse citas aceptadas.'), 409
    db.execute("UPDATE appointments SET status='completada',updated_at=CURRENT_TIMESTAMP WHERE id=?", (appointment_id,))
    services = db.execute('SELECT service_id FROM appointment_services WHERE appointment_id=?', (appointment_id,)).fetchall()
    for service in services:
        consumptions = db.execute('SELECT product_id,quantity FROM service_consumption WHERE service_id=?', (service['service_id'],)).fetchall()
        for consumption in consumptions:
            product = db.execute('SELECT stock,name FROM products WHERE id=?', (consumption['product_id'],)).fetchone()
            if not product or product['stock'] < consumption['quantity']:
                db.rollback()
                return jsonify(error=f'Existencia insuficiente para insumo: {product["name"] if product else "desconocido"}.'), 409
            db.execute('UPDATE products SET stock=stock-? WHERE id=?', (consumption['quantity'], consumption['product_id']))
            db.execute('INSERT INTO inventory_movements(product_id,movement_type,quantity,reason,status,requested_by,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                       (consumption['product_id'], 'consumo', consumption['quantity'], f'Consumo de cita #{appointment_id}', 'aprobado', actor['id'], actor['id']))
    audit(db, 'completar_cita', 'appointment', appointment_id)
    db.commit()
    return jsonify(message='Servicio completado e insumos descontados.')


@api.post('/inventory/movements')
@roles_required('inventory', 'admin')
def request_inventory_movement():
    data, db, actor = payload(), get_db(), current_actor()
    try:
        product_id, quantity = int(data.get('product_id')), int(data.get('quantity'))
        movement_type = data.get('movement_type')
        reason = str(data.get('reason', '')).strip()
        if movement_type not in ('entrada', 'salida', 'ajuste', 'merma') or quantity <= 0 or not reason:
            raise ValueError('Tipo, cantidad positiva y motivo son obligatorios.')
        product = db.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone()
        if not product:
            raise ValueError('Producto no encontrado.')
        status = 'aprobado' if actor['role'] == 'admin' else 'pendiente'
        cur = db.execute('INSERT INTO inventory_movements(product_id,movement_type,quantity,reason,status,requested_by,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,?)',
                         (product_id, movement_type, quantity, reason, status, actor['id'], actor['id'] if status == 'aprobado' else None,
                          datetime.now(timezone.utc).isoformat() if status == 'aprobado' else None))
        if status == 'aprobado':
            apply_inventory_change(db, product_id, movement_type, quantity)
        audit(db, 'solicitar_movimiento', 'inventory_movement', cur.lastrowid, {'product_id': product_id, 'status': status})
        db.commit()
        return jsonify(id=cur.lastrowid, status=status, message='Movimiento registrado.'), 201
    except (ValueError, TypeError) as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400


def apply_inventory_change(db, product_id, movement_type, quantity):
    product = db.execute('SELECT stock FROM products WHERE id=?', (product_id,)).fetchone()
    delta = quantity if movement_type == 'entrada' else -quantity
    if movement_type in ('salida', 'merma') and product['stock'] < quantity:
        raise ValueError('Existencia insuficiente para este movimiento.')
    if movement_type == 'ajuste':
        db.execute('UPDATE products SET stock=? WHERE id=?', (quantity, product_id))
    else:
        db.execute('UPDATE products SET stock=stock+? WHERE id=?', (delta, product_id))


@api.get('/inventory/movements')
@roles_required('admin', 'inventory', 'specialist')
def list_inventory_movements():
    rows = get_db().execute('''SELECT m.*,p.name AS product_name,e.full_name AS requester
                               FROM inventory_movements m JOIN products p ON p.id=m.product_id
                               LEFT JOIN employees e ON e.id=m.requested_by ORDER BY m.id DESC LIMIT 300''').fetchall()
    return jsonify(items=[serialize(row) for row in rows])


@api.patch('/inventory/movements/<int:movement_id>/approve')
@roles_required('admin')
def approve_inventory_movement(movement_id):
    data, db = payload(), get_db()
    row = db.execute('SELECT * FROM inventory_movements WHERE id=?', (movement_id,)).fetchone()
    if not row or row['status'] != 'pendiente':
        return jsonify(error='Movimiento inexistente o ya procesado.'), 404
    status = 'rechazado' if data.get('approve') is False else 'aprobado'
    try:
        if status == 'aprobado':
            apply_inventory_change(db, row['product_id'], row['movement_type'], row['quantity'])
        db.execute('UPDATE inventory_movements SET status=?,approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=?',
                   (status, actor_id_for_employee(), movement_id))
        audit(db, status, 'inventory_movement', movement_id)
        db.commit()
        return jsonify(message=f'Movimiento {status}.')
    except ValueError as exc:
        db.rollback()
        return jsonify(error=str(exc)), 409


@api.post('/sales')
@roles_required('cashier', 'admin')
def create_sale():
    data, db, actor = payload(), get_db(), current_actor()
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify(error='Agrega al menos un producto o servicio.'), 400
    method = data.get('payment_method')
    if method not in ('efectivo', 'transferencia'):
        return jsonify(error='Método de pago inválido.'), 400
    db.execute('BEGIN IMMEDIATE')
    try:
        discount = money(data.get('discount', 0))
        if discount and actor['role'] != 'admin':
            raise ValueError('Solo administración puede autorizar descuentos.')
        resolved, subtotal = [], 0
        for item in items:
            kind = item.get('item_type')
            item_id, quantity = int(item.get('item_id')), int(item.get('quantity', 1))
            if quantity <= 0 or quantity > 1000:
                raise ValueError('Cantidad inválida.')
            table = 'products' if kind == 'producto' else 'services' if kind == 'servicio' else None
            if not table:
                raise ValueError('Tipo de artículo inválido.')
            source = db.execute(f'SELECT * FROM {table} WHERE id=? AND active=1', (item_id,)).fetchone()
            if not source:
                raise ValueError('Artículo no encontrado.')
            unit_price = source['price_cents']
            if kind == 'producto' and source['stock'] < quantity:
                raise ValueError(f'Existencia insuficiente: {source["name"]}.')
            line_total = unit_price * quantity
            subtotal += line_total
            resolved.append((kind, item_id, source['name'], quantity, unit_price, line_total))
        if discount > subtotal:
            raise ValueError('El descuento no puede superar el subtotal.')
        total = subtotal - discount
        if total <= 0:
            raise ValueError('El total debe ser mayor que cero.')
        cur = db.execute('INSERT INTO sales(client_id,cashier_id,subtotal_cents,discount_cents,total_cents,payment_method) VALUES(?,?,?,?,?,?)',
                         (data.get('client_id'), actor['id'], subtotal, discount, total, method))
        for kind, item_id, name, qty, price, line in resolved:
            db.execute('INSERT INTO sale_items(sale_id,item_type,item_id,item_name,quantity,unit_price_cents,line_total_cents) VALUES(?,?,?,?,?,?,?)',
                       (cur.lastrowid, kind, item_id, name, qty, price, line))
            if kind == 'producto':
                db.execute('UPDATE products SET stock=stock-? WHERE id=?', (qty, item_id))
                db.execute('INSERT INTO inventory_movements(product_id,movement_type,quantity,reason,status,requested_by,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                           (item_id, 'venta', qty, f'Venta #{cur.lastrowid}', 'aprobado', actor['id'], actor['id']))
        audit(db, 'crear_venta', 'sale', cur.lastrowid, {'total_cents': total, 'payment_method': method})
        db.commit()
        return jsonify(id=cur.lastrowid, subtotal_cents=subtotal, discount_cents=discount, total_cents=total, message='Venta registrada.'), 201
    except (ValueError, TypeError) as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400


@api.get('/sales')
@roles_required('admin', 'cashier')
def list_sales():
    rows = get_db().execute('''SELECT s.*,c.full_name AS client_name,e.full_name AS cashier_name
                               FROM sales s LEFT JOIN clients c ON c.id=s.client_id
                               LEFT JOIN employees e ON e.id=s.cashier_id ORDER BY s.id DESC LIMIT 200''').fetchall()
    result = []
    db = get_db()
    for row in rows:
        item = serialize(row)
        item['items'] = [serialize(x) for x in db.execute('SELECT * FROM sale_items WHERE sale_id=?', (row['id'],)).fetchall()]
        result.append(item)
    return jsonify(items=result)


@api.post('/expenses')
@roles_required('admin')
def create_expense():
    data, db = payload(), get_db()
    try:
        description = str(data.get('description', '')).strip()
        amount = money(data.get('amount', 0))
        if not description or amount <= 0:
            raise ValueError('Descripción e importe mayor que cero son obligatorios.')
        cur = db.execute('INSERT INTO expenses(description,amount_cents,category,created_by) VALUES(?,?,?,?)',
                         (description, amount, str(data.get('category', 'general')).strip(), actor_id_for_employee()))
        audit(db, 'crear_gasto', 'expense', cur.lastrowid)
        db.commit()
        return jsonify(id=cur.lastrowid, message='Gasto registrado.'), 201
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@api.get('/dashboard')
@roles_required('admin', 'cashier', 'inventory')
def dashboard():
    db = get_db()
    sales = db.execute('SELECT COALESCE(SUM(total_cents),0) AS total, COUNT(*) AS count FROM sales WHERE date(created_at)=date(\'now\')').fetchone()
    expenses = db.execute('SELECT COALESCE(SUM(amount_cents),0) AS total FROM expenses WHERE date(created_at)=date(\'now\')').fetchone()
    stock_low = db.execute('SELECT COUNT(*) AS n FROM products WHERE active=1 AND stock<=min_stock').fetchone()['n']
    pending = db.execute("SELECT COUNT(*) AS n FROM appointments WHERE status='pendiente'").fetchone()['n']
    movements = db.execute("SELECT COUNT(*) AS n FROM inventory_movements WHERE status='pendiente'").fetchone()['n']
    return jsonify(today_sales_cents=sales['total'], today_sales_count=sales['count'], today_expenses_cents=expenses['total'],
                   low_stock=stock_low, pending_appointments=pending, pending_movements=movements)


@api.get('/clients')
@roles_required('admin', 'cashier')
def list_clients():
    rows = get_db().execute('SELECT id,full_name,phone,created_at FROM clients WHERE active=1 ORDER BY full_name LIMIT 500').fetchall()
    return jsonify(items=[serialize(r) for r in rows])


@api.get('/audit')
@roles_required('admin')
def list_audit():
    rows = get_db().execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 300').fetchall()
    return jsonify(items=[serialize(r) for r in rows])


@api.get('/profile')
@roles_required('customer')
def profile():
    actor = current_actor()
    db = get_db()
    client = db.execute('SELECT id,full_name,phone,created_at FROM clients WHERE id=?', (actor['id'],)).fetchone()
    appointments = db.execute('''SELECT a.id,a.starts_at,a.ends_at,a.status,e.full_name AS barber_name
                                 FROM appointments a LEFT JOIN employees e ON e.id=a.barber_id
                                 WHERE a.client_id=? ORDER BY a.starts_at DESC LIMIT 100''', (actor['id'],)).fetchall()
    return jsonify(client=serialize(client), appointments=[serialize(x) for x in appointments])


@api.get('/employees/barbers')
@login_required
def list_barbers():
    rows = get_db().execute("SELECT id,full_name FROM employees WHERE role='barber' AND active=1 ORDER BY full_name").fetchall()
    return jsonify(items=[serialize(x) for x in rows])

@api.post('/employees')
@roles_required('admin')
def create_employee():
    data, db = payload(), get_db()
    name, role, code = str(data.get('full_name', '')).strip(), data.get('role'), str(data.get('code', '')).strip()
    if not name or role not in ('barber', 'specialist', 'inventory', 'cashier') or not re.fullmatch(r'\d{10}', code):
        return jsonify(error='Nombre, rol válido y código de 10 dígitos son obligatorios.'), 400
    for existing in db.execute('SELECT code_hash FROM employees'):
        if verify_secret(code, existing['code_hash']):
            return jsonify(error='Ese código ya está asignado.'), 409
    cur = db.execute('INSERT INTO employees(full_name,role,code_hash) VALUES(?,?,?)', (name, role, hash_secret(code)))
    audit(db, 'crear_empleado', 'employee', cur.lastrowid, {'role': role, 'name': name})
    db.commit()
    return jsonify(id=cur.lastrowid, message='Empleado creado. Guarda el código en un lugar seguro.'), 201


@api.patch('/employees/<int:employee_id>')
@roles_required('admin')
def update_employee(employee_id):
    data, db = payload(), get_db()
    employee = db.execute('SELECT * FROM employees WHERE id=?', (employee_id,)).fetchone()
    if not employee:
        return jsonify(error='Empleado no encontrado.'), 404
    name = str(data.get('full_name', employee['full_name'])).strip()
    active = int(bool(data.get('active', employee['active'])))
    code = data.get('code')
    if code is not None:
        code = str(code).strip()
        if not re.fullmatch(r'\d{10}', code):
            return jsonify(error='El código debe contener 10 dígitos.'), 400
        for other in db.execute('SELECT id,code_hash FROM employees WHERE id<>?', (employee_id,)):
            if verify_secret(code, other['code_hash']):
                return jsonify(error='Ese código ya está asignado.'), 409
        db.execute('UPDATE employees SET full_name=?,active=?,code_hash=? WHERE id=?', (name, active, hash_secret(code), employee_id))
    else:
        db.execute('UPDATE employees SET full_name=?,active=? WHERE id=?', (name, active, employee_id))
    audit(db, 'actualizar_empleado', 'employee', employee_id, {'active': active, 'code_reset': code is not None})
    db.commit()
    return jsonify(message='Empleado actualizado.')


@api.patch('/appointments/<int:appointment_id>/reassign')
@roles_required('admin')
def reassign_appointment(appointment_id):
    data, db = payload(), get_db()
    row = db.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,)).fetchone()
    if not row or row['status'] in ('cancelada', 'completada'):
        return jsonify(error='Cita no encontrada o no reasignable.'), 404
    try:
        barber_id = int(data.get('barber_id'))
        barber = db.execute("SELECT id FROM employees WHERE id=? AND role='barber' AND active=1", (barber_id,)).fetchone()
        if not barber:
            raise ValueError('Barbero no válido.')
        if not valid_appointment_slot(db, barber_id, row['starts_at'], row['ends_at'], appointment_id):
            raise ValueError('El barbero ya tiene una cita en ese horario.')
        db.execute("UPDATE appointments SET barber_id=?,status='reasignada',updated_at=CURRENT_TIMESTAMP WHERE id=?", (barber_id, appointment_id))
        audit(db, 'reasignar_cita', 'appointment', appointment_id, {'barber_id': barber_id, 'reason': str(data.get('reason', '')).strip()})
        db.commit()
        return jsonify(message='Cita reasignada.')
    except (ValueError, TypeError) as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400


@api.put('/services/<int:service_id>/consumption')
@roles_required('admin')
def set_service_consumption(service_id):
    data, db = payload(), get_db()
    if not db.execute('SELECT id FROM services WHERE id=?', (service_id,)).fetchone():
        return jsonify(error='Servicio no encontrado.'), 404
    consumptions = data.get('items', [])
    if not isinstance(consumptions, list):
        return jsonify(error='Formato de consumos inválido.'), 400
    try:
        db.execute('DELETE FROM service_consumption WHERE service_id=?', (service_id,))
        for item in consumptions:
            product_id, quantity = int(item['product_id']), int(item['quantity'])
            if quantity <= 0 or not db.execute('SELECT id FROM products WHERE id=?', (product_id,)).fetchone():
                raise ValueError('Producto o cantidad inválidos.')
            db.execute('INSERT INTO service_consumption(service_id,product_id,quantity) VALUES(?,?,?)', (service_id, product_id, quantity))
        audit(db, 'configurar_consumos', 'service', service_id, {'items': consumptions})
        db.commit()
        return jsonify(message='Consumos del servicio guardados.')
    except (ValueError, KeyError, TypeError) as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400
