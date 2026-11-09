from pathlib import Path
from dotenv import load_dotenv
from app import create_app

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
app = create_app()

if __name__ == '__main__':
    print('\nLEGENDARY BARBER')
    print('Abre: http://127.0.0.1:5000')
    print('Base de datos: instance/legendary_barber.sqlite3')
    print('Los códigos OTP de desarrollo aparecen en esta terminal.')
    app.run(host='127.0.0.1', port=5000, debug=app.config['DEBUG'])
