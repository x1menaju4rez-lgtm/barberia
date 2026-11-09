# LEGENDARY BARBER — Proyecto para Visual Studio Code

Aplicación web para una barbería de una sucursal. Incluye frontend HTML/CSS/JavaScript, backend Flask y base de datos SQLite persistente. El paquete incluye una base inicial con 16 empleados, 41 servicios y 28 productos; si eliminas el archivo de base, el servidor vuelve a crear el esquema y los datos iniciales automáticamente en `instance/legendary_barber.sqlite3`.

## 1. Requisitos

- Windows 10/11, macOS o Linux.
- Python 3.10 o posterior.
- Visual Studio Code y la extensión oficial de Python.

## 2. Instalación en Windows

Abre la carpeta `LegendaryBarber_VSCode` en Visual Studio Code. En **Terminal > New Terminal**, ejecuta:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Abre `.env` y cambia al menos:

- `SECRET_KEY`: una cadena aleatoria larga y privada.
- `LEGENDARY_ADMIN_PASSWORD`: la contraseña exclusiva de la administradora. No es el código numérico.

Después ejecuta:

```powershell
python run.py
```

Abre `http://127.0.0.1:5000` en el navegador. Si PowerShell bloquea la activación del entorno, ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y vuelve a activar `.venv`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edita .env y cambia los secretos
python run.py
```

## 3. Accesos iniciales de desarrollo

Los códigos iniciales del personal se cargan desde `app/seed.py`, en el servidor, nunca desde JavaScript del navegador. Son los códigos privados entregados en la especificación de Legendary Barber. La cuenta administradora requiere **dos factores de acceso local**: su código de 10 dígitos y `LEGENDARY_ADMIN_PASSWORD` del archivo `.env`. En la primera ejecución, crea/configura el `.env` antes de usar el panel administrativo.

Para mantener la confidencialidad, no publiques el proyecto ni `app/seed.py` en repositorios abiertos mientras conserve códigos iniciales. En producción, sustituye los códigos por nuevos valores y guarda los secretos en el administrador de secretos del proveedor de hosting. Los códigos ya se almacenan como hash scrypt en la base de datos.

## 4. Registro de clientes y OTP

El cliente escribe nombre y teléfono mexicano de 10 dígitos. Para iniciar sesión otra vez, deja el campo de nombre vacío. El sistema genera un código de verificación de seis dígitos con vencimiento de cinco minutos.

**Modo local:** el código OTP aparece en la terminal donde está corriendo `python run.py`. No se envía SMS real. Para producción hay que conectar un proveedor de SMS, adaptar `request_otp()` y guardar las credenciales como secretos. No actives `SMS_PROVIDER_CONFIGURED=1` sin implementar y probar dicho proveedor.

## 5. Base de datos

SQLite no requiere instalar un servidor independiente. El archivo se crea automáticamente en:

`instance/legendary_barber.sqlite3`

Tablas incluidas: clientes, empleados, OTP, servicios, productos, consumos por servicio, citas, servicios de cada cita, movimientos de inventario, ventas, partidas de venta, gastos, intentos de acceso y auditoría.

Para una copia de respaldo, detén la aplicación y copia el archivo de base de datos. Para producción con varias instancias o mucho tráfico, migra a PostgreSQL y configura `DATABASE_PATH`/la capa de persistencia correspondiente antes de desplegar.

## 6. Funciones implementadas

- Registro y acceso de clientes mediante OTP de desarrollo.
- Acceso por código de empleado; contraseña adicional para administración.
- Roles: administradora, barbero, especialista, inventario y cajero.
- Catálogo de servicios y productos con publicación controlada.
- Gestión administrativa de servicios y productos.
- Registro administrativo de citas, validación de máximo tres servicios y prevención de solapamientos por barbero.
- Aceptar/rechazar citas, reasignar por administración y cancelar sin penalización por cercanía.
- Descuento de insumos al completar una cita si se configuraron consumos.
- Solicitudes y aprobación de movimientos de inventario.
- Venta de productos, pago en efectivo/transferencia y descuento de existencias.
- Gastos, indicadores básicos y auditoría.
- PWA con manifest y caché estática básica.

## 7. Endurecimiento antes de publicar

Esta es una base funcional para desarrollo local, no una instalación auditada para producción. Antes de publicarla:

1. Usa HTTPS y establece `COOKIE_SECURE=1` y `FLASK_DEBUG=0`.
2. Configura `SECRET_KEY` y `LEGENDARY_ADMIN_PASSWORD` fuertes y únicos.
3. Cambia los códigos de acceso iniciales; no subas `.env`, la base de datos ni credenciales a Git.
4. Conecta SMS real para OTP y notificaciones push si las necesitas.
5. Configura horarios, comidas, descansos, vacaciones y reglas de disponibilidad; la versión inicial evita solapamientos pero todavía no tiene un editor de turnos.
6. Prueba recuperación de cuenta con verificación de identidad y agrega el flujo administrativo completo antes de usarlo con clientes reales.
7. Configura backups cifrados y monitoreo.

El service worker solo almacena recursos estáticos. No guarda ni intenta sincronizar pagos, citas, inventario o datos privados sin conexión.

## 8. Pruebas rápidas

```bash
python -m compileall app run.py
```

Verifica que `http://127.0.0.1:5000/api/health` responda JSON con `status: ok` y que el archivo SQLite aparezca en `instance/`.

## 9. Importante

No se inventan precios: los servicios y productos iniciales empiezan con precio $0 y sin publicación; la administradora debe configurar precios antes de publicarlos o venderlos. El logotipo está representado provisionalmente por las letras LB; coloca el archivo de marca en `static/assets/` y actualiza el encabezado cuando tengas el PNG/SVG oficial.
