import os
import secrets
import sqlite3
import logging
import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, g
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from PIL import Image
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))
app.permanent_session_lifetime = timedelta(minutes=10)

socketio = SocketIO(app, cors_allowed_origins="*")

# Tạo thư mục lưu ảnh debug
DEBUG_IMAGE_DIR = "debug_images"
if not os.path.exists(DEBUG_IMAGE_DIR):
    os.makedirs(DEBUG_IMAGE_DIR)

# Database connection
def get_db_connection():
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = sqlite3.connect('warehouse.db', check_same_thread=False)
        g.sqlite_db.row_factory = sqlite3.Row
    return g.sqlite_db

# Đóng kết nối khi request kết thúc
@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()
        logger.debug("Database connection closed")

# Initialize database
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS admin 
                 (admin_id TEXT PRIMARY KEY, password TEXT, tel TEXT, job_num TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (id INTEGER PRIMARY KEY, qr_code TEXT, name TEXT, weight REAL, 
                  quantity INTEGER DEFAULT 1, timestamp TEXT, 
                  UNIQUE(qr_code, name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS sensor_data 
                 (id INTEGER PRIMARY KEY, temperature REAL, humidity REAL, weight REAL, 
                  timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS QRdate
                 (id INTEGER PRIMARY KEY, qr_code TEXT UNIQUE, name TEXT, timestamp TEXT)''')
    conn.commit()
    logger.info("Database initialized successfully")


with app.app_context():
    init_db()

# Middleware to check login
def login_required(f):
    def wrap(*args, **kwargs):
        if not session.get('flag'):
            flash("Please log in to access this page.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('id')
        user_pw = request.form.get('pw')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT admin_id, password FROM admin WHERE admin_id = ? AND password = ?", (user_id, user_pw))
        admin = cur.fetchone()

        if admin:
            flash("Welcome, Admin.")
            session.permanent = True
            session['flag'] = True
            return redirect(url_for('index'))
        flash("Login failure.")
        return redirect(url_for('login'))
    return render_template('login.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form.get('id')
        user_pw = request.form.get('pw')
        user_tel = request.form.get('tel')
        user_job_num = request.form.get('job_num')

        if not user_id or not user_pw or not user_tel or not user_job_num:
            flash("All fields are required!")
            return redirect(url_for('register'))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO admin (admin_id, password, tel, job_num) VALUES (?, ?, ?, ?)",
                        (user_id, user_pw, user_tel, user_job_num))
            conn.commit()
            flash("Registration successful! Please log in.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Registration failed. User ID might already exist.")
            return redirect(url_for('register'))
    return render_template('register.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('flag', None)
    flash("You have been logged out.")
    return redirect(url_for('login'))

# Main page (protected)
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT * FROM sensor_data 
                 WHERE timestamp >= datetime('now', '-24 hours')
                 ORDER BY timestamp DESC''')
    all_data = c.fetchall()

    sensor_data = []
    last_time = None
    for row in all_data:
        current_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        if last_time is None or (last_time - current_time).total_seconds() >= 3600:
            sensor_data.append(row)
            last_time = current_time
        if len(sensor_data) >= 10:
            break

    inventory = conn.execute('SELECT * FROM inventory ORDER BY timestamp DESC').fetchall()
    return render_template('index.html', sensor_data=sensor_data, inventory=inventory)

# API to receive sensor data from ESP32-DHT11-HX711 and store in database
@app.route('/api/sensor', methods=['POST'])
def sensor_data():
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        temperature = data.get('temperature')
        humidity = data.get('humidity')
        weight = data.get('weight')

        if temperature is None or humidity is None:
            return jsonify({'status': 'error', 'message': 'Temperature and humidity are required'}), 400

        if not isinstance(temperature, (int, float)) or not isinstance(humidity, (int, float)):
            return jsonify({'status': 'error', 'message': 'Temperature and humidity must be numbers'}), 400

        if weight is not None and (not isinstance(weight, (int, float)) or weight < 0):
            return jsonify({'status': 'error', 'message': 'Weight must be a non-negative number'}), 400

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO sensor_data (temperature, humidity, weight, timestamp) 
                     VALUES (?, ?, ?, ?)''', 
                  (temperature, humidity, weight, current_time))
        conn.commit()

        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# API to handle QR code scanning
@app.route('/upload_image', methods=['POST'])
def upload_image():
    try:
        logger.debug("Received image upload request")
        if 'image' not in request.files:
            logger.error("No image provided in request")
            return jsonify({'status': 'error', 'message': 'No image provided'}), 400

        image_file = request.files['image']
        if image_file.filename == '':
            logger.error("Empty image filename")
            return jsonify({'status': 'error', 'message': 'No image selected'}), 400

        image_file.seek(0)

        try:
            logger.debug("Processing uploaded image")
            image = Image.open(image_file)
            image_np = np.array(image)
            if len(image_np.shape) == 3 and image_np.shape[2] == 4:
                image_np = image_np[:, :, :3]

            qr_detector = cv2.QRCodeDetector()
            qr_data, points, _ = qr_detector.detectAndDecode(image_np)
            if not qr_data:
                logger.debug("Attempting to decode QR code from grayscale image")
                gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
                qr_data, points, _ = qr_detector.detectAndDecode(gray)
                if not qr_data:
                    logger.warning("No QR code detected in image")
                    return jsonify({'status': 'error', 'message': 'No QR code detected'}), 404

            qr_code = qr_data
            logger.info(f"QR code detected: {qr_code}")

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = get_db_connection()
            c = conn.cursor()
            try:
                c.execute('''INSERT INTO QRdate (qr_code, name, timestamp) 
                             VALUES (?, ?, ?)''', 
                         (qr_code, 'QR Item', current_time))
                conn.commit()
                logger.info(f"QR code saved to database: {qr_code}")
            except sqlite3.IntegrityError:
                conn.close()
                logger.warning(f"QR code already exists: {qr_code}")
                return jsonify({'status': 'error', 'message': 'QR code already exists'}), 409
            finally:
                conn.close()

            # Phát sự kiện WebSocket khi có dữ liệu mới
            logger.debug("Emitting WebSocket event for new QR data")
            socketio.emit('new_qr_data', {
                'qr_code': qr_code,
                'timestamp': current_time
            })

            latest_data_response = requests.get('http://localhost:5000/api/latest_data', timeout=5)
            if latest_data_response.status_code == 200:
                latest_data = latest_data_response.json()
                return jsonify({
                    'status': 'success',
                    'qr_code': qr_code,
                    'timestamp': current_time,
                    'latest_data': latest_data
                }), 200
            else:
                logger.warning("Failed to retrieve latest data")
                return jsonify({
                    'status': 'success',
                    'qr_code': qr_code,
                    'timestamp': current_time,
                    'latest_data': None,
                    'message': 'Failed to retrieve latest data'
                }), 200

        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}")
            return jsonify({'status': 'error', 'message': 'Invalid image format'}), 400
    except Exception as e:
        logger.error(f"Error processing QR code image: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Internal server error: {str(e)}'}), 500

# API to get the latest QR code and sensor data
@app.route('/api/latest_data', methods=['GET'])
def get_latest_data():  
    logger.debug("Fetching latest QR code and sensor data")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT qr_code, name, timestamp FROM QRdate ORDER BY timestamp DESC LIMIT 1')
    qr_data = c.fetchone()
    c.execute('SELECT temperature, humidity, timestamp FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
    sensor_data = c.fetchone()
    conn.close()

    response = {}
    if qr_data:
        logger.debug(f"Latest QR code found: {qr_data[0]}")
        response.update({
            'qr_code': qr_data[0],
            'name': qr_data[1],
            'qr_timestamp': qr_data[2]
        })
    else:
        logger.debug("No QR data found")
    
    if sensor_data:
        response.update({
            'temperature': sensor_data[0],
            'humidity': sensor_data[1],
            'sensor_timestamp': sensor_data[2]
        })
    return jsonify(response)

# API to handle import action
@app.route('/api/import_item', methods=['POST'])
@login_required
def import_item():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data received for import_item")
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        qr_code = data.get('qr_code')
        name = data.get('name')
        weight = data.get('weight')

        logger.debug(f"Received import request: qr_code={qr_code}, name={name}, weight={weight}")

        if not qr_code or not name or weight is None:
            logger.error("Missing qr_code, name, or weight")
            return jsonify({'status': 'error', 'message': 'QR code, name, and weight are required'}), 400

        

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO inventory (qr_code, name, weight, quantity, timestamp) 
                         VALUES (?, ?, ?, 1, ?)''', 
                         (qr_code, name, weight, current_time))
            conn.commit()
            logger.info(f"Item imported: qr_code={qr_code}, name={name}, weight={weight}")
            return jsonify({'status': 'success', 'message': 'Item imported successfully'})
        except sqlite3.IntegrityError:
            c.execute('''UPDATE inventory SET quantity = quantity + 1, weight = ?, timestamp = ? 
                         WHERE qr_code = ? AND name = ?''',
                         (weight, current_time, qr_code, name))
            conn.commit()
            logger.info(f"Item quantity updated: qr_code={qr_code}, name={name}, weight={weight}")
            return jsonify({'status': 'success', 'message': 'Item quantity updated successfully'})
    except Exception as e:
        logger.error(f"Error importing item: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# API to handle export action
@app.route('/api/export_item', methods=['POST'])
@login_required
def export_item():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data received for export_item")
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        qr_code = data.get('qr_code')
        name = data.get('name')

        logger.debug(f"Received export request: qr_code={qr_code}, name={name}")

        if not qr_code or not name:
            logger.error("Missing qr_code or name")
            return jsonify({'status': 'error', 'message': 'QR code and name are required'}), 400

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT quantity FROM inventory WHERE qr_code = ? AND name = ?', (qr_code, name))
        row = c.fetchone()
        if not row:
            logger.warning(f"No item found with qr_code: {qr_code}, name={name}")
            return jsonify({'status': 'error', 'message': 'No such product in inventory'}), 404

        quantity = row['quantity']
        if quantity > 1:
            c.execute('UPDATE inventory SET quantity = quantity - 1 WHERE qr_code = ? AND name = ?', (qr_code, name))
        else:
            c.execute('DELETE FROM inventory WHERE qr_code = ? AND name = ?', (qr_code, name))
        conn.commit()
        logger.info(f"Item exported: qr_code={qr_code}, name={name}")
        return jsonify({'status': 'success', 'message': 'Item exported successfully'})
    except Exception as e:
        logger.error(f"Error exporting item: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500




# API to get sensor data (real-time)
@app.route('/api/sensor_data', methods=['GET'])
@login_required
def get_sensor_data():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
        row = c.fetchone()

        if row:
            return jsonify({
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'timestamp': row['timestamp']
            })
        return jsonify({'status': 'error', 'message': 'No sensor data available'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# API to get sensor data history (hourly)
@app.route('/api/sensor_data_history', methods=['GET'])
@login_required
def get_sensor_data_history():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT * FROM sensor_data 
                     WHERE timestamp >= datetime('now', '-24 hours')
                     ORDER BY timestamp DESC''')
        all_data = c.fetchall()

        sensor_data = []
        last_time = None
        for row in all_data:
            current_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
            if last_time is None or (last_time - current_time).total_seconds() >= 3600:
                sensor_data.append({
                    'temperature': row['temperature'],
                    'humidity': row['humidity'],
                    'weight': row['weight'],
                    'timestamp': row['timestamp']
                })
                last_time = current_time
            if len(sensor_data) >= 10:
                break

        return jsonify(sensor_data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# API to get inventory list
@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM inventory')
        rows = c.fetchall()

        inventory = [
            {'id': row['id'], 'qr_code': row['qr_code'], 'name': row['name'], 'weight': row['weight'], 
             'quantity': row['quantity'], 'timestamp': row['timestamp']}
            for row in rows
        ]
        logger.debug(f"Retrieved {len(inventory)} inventory items")
        return jsonify(inventory)
    except Exception as e:
        logger.error(f"Error retrieving inventory: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)