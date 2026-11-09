from .security import hash_secret

STAFF_SEED = [
    ('Administradora principal', 'admin', '2541500260'),
    ('Barbero 1', 'barber', '2541500001'),
    ('Barbero 2', 'barber', '2541500002'),
    ('Barbero 3', 'barber', '2541500003'),
    ('Barbero 4', 'barber', '2541500004'),
    ('Barbero 5', 'barber', '2541500005'),
    ('Especialista tratamientos 1', 'specialist', '2541500021'),
    ('Especialista tratamientos 2', 'specialist', '2541500022'),
    ('Especialista tratamientos 3', 'specialist', '2541500023'),
    ('Encargado inventario 1', 'inventory', '2541500321'),
    ('Encargado inventario 2', 'inventory', '2541500322'),
    ('Encargado inventario 3', 'inventory', '2541500323'),
    ('Encargado inventario 4', 'inventory', '2541500324'),
    ('Encargado inventario 5', 'inventory', '2541500325'),
    ('Cajero 1', 'cashier', '2541500431'),
    ('Cajero 2', 'cashier', '2541500432'),
]

SERVICES = {
    'Cortes y estilizado': ['Clásico', 'Moderno', 'Fade', 'Taper fade', 'Militar', 'Corte con tijera', 'Diseños', 'Perfilado', 'Rapado', 'Lavado', 'Secado', 'Peinado', 'Asesoría'],
    'Tratamientos capilares cosméticos': ['Hidratación', 'Nutrición', 'Reparación cosmética', 'Exfoliación capilar', 'Limpieza capilar', 'Mascarillas'],
    'Colorimetría': ['Tintes', 'Cobertura de canas', 'Matización', 'Mechas', 'Luces', 'Decoloración', 'Tonos fantasía', 'Corrección de color'],
    'Faciales': ['Limpieza facial', 'Exfoliación facial', 'Mascarillas faciales', 'Hidratación facial', 'Cuidado cosmético de poros', 'Masaje relajante', 'Contorno de ojos'],
    'Barba y bigote': ['Diseño', 'Perfilado', 'Recorte', 'Afeitado clásico', 'Toalla caliente', 'Hidratación', 'Acondicionamiento'],
}

PRODUCTS = [
    'Cera', 'Pomada', 'Gel', 'Crema para peinar', 'Polvo texturizador', 'Spray', 'Shampoo', 'Acondicionador',
    'Mascarilla capilar', 'Sérum', 'Aceite para barba', 'Bálsamo para barba', 'Limpiador facial', 'Hidratante facial',
    'Protector solar', 'Exfoliante', 'Cepillo', 'Peine', 'Espejo', 'Rastrillo/maquinilla', 'Hojas de repuesto',
    'Brocha', 'Tazón', 'Capa', 'Atomizador', 'Esponja para rizos', 'Neceser', 'Toalla'
]


def seed_database(db):
    employees = db.execute('SELECT COUNT(*) AS n FROM employees').fetchone()['n']
    if employees == 0:
        db.executemany(
            'INSERT INTO employees(full_name, role, code_hash) VALUES(?,?,?)',
            [(name, role, hash_secret(code)) for name, role, code in STAFF_SEED]
        )
    services_count = db.execute('SELECT COUNT(*) AS n FROM services').fetchone()['n']
    if services_count == 0:
        rows = []
        for category, names in SERVICES.items():
            for name in names:
                rows.append((category, name, '', 0, 30, 0, 0))
        db.executemany(
            'INSERT INTO services(category,name,description,price_cents,duration_minutes,active,published) VALUES(?,?,?,?,?,?,?)', rows
        )
    products_count = db.execute('SELECT COUNT(*) AS n FROM products').fetchone()['n']
    if products_count == 0:
        db.executemany(
            'INSERT INTO products(name,description,brand,price_cents,cost_cents,stock,min_stock,supplier,active,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
            [(name, '', '', 0, 0, 0, 0, '', 1, 0) for name in PRODUCTS]
        )
    db.commit()
