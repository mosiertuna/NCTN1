import sys
import os
import secrets
import logging
import cv2 
import numpy as np
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, g
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from PIL import Image
from io import BytesIO
import sqlite3

instance_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance')
sys.path.append(instance_path)

from database import get_db_connection, close_db, init_db

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Khởi tạo ứng dụng Flask
app = Flask(__name__, 
            template_folder='../templates',  
            static_folder='../static')      
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

socketio = SocketIO(app, cors_allowed_origins="*")

app.teardown_appcontext(close_db)

with app.app_context():
    init_db()

def login_required(f):
    """Decorator để yêu cầu người dùng đăng nhập trước khi truy cập route."""
    def wrap(*args, **kwargs):
        if not session.get('flag'):
            flash("Please log in to access this page.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__ 
    return wrap

# ----- Authentication Routes -----
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

@app.route('/logout')
def logout():
    session.pop('flag', None)
    flash("You have been logged out.")
    return redirect(url_for('login'))

# ----- Main Routes -----
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Lấy dữ liệu cảm biến 24h gần nhất, lọc theo giờ
    c.execute('''SELECT * FROM sensor_data
                 WHERE timestamp >= datetime('now', '-24 hours')
                 ORDER BY timestamp DESC''')
    all_sensor_data = c.fetchall()

    sensor_data_filtered = []
    last_time = None
    for row in all_sensor_data:
        current_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        if last_time is None or (last_time - current_time).total_seconds() >= 3600:
            sensor_data_filtered.append(row)
            last_time = current_time
        if len(sensor_data_filtered) >= 10: 
            break

    # Lấy dữ liệu hàng tồn kho
    inventory = conn.execute('SELECT * FROM inventory ORDER BY timestamp DESC').fetchall()
    return render_template('index.html', sensor_data=sensor_data_filtered, inventory=inventory)

# ----- API Routes: Sensor Data -----
@app.route('/api/sensor', methods=['POST'])
def sensor_data_api():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data provided for sensor_data_api")
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        temperature = data.get('temperature')
        humidity = data.get('humidity')
        weight = data.get('weight')

        # Validation
        if temperature is None or humidity is None:
            return jsonify({'status': 'error', 'message': 'Temperature and humidity are required'}), 400

        if not isinstance(temperature, (int, float)) or not isinstance(humidity, (int, float)):
            return jsonify({'status': 'error', 'message': 'Temperature and humidity must be numbers'}), 400

        if weight is not None and (not isinstance(weight, (int, float)) or weight < 0):
            return jsonify({'status': 'error', 'message': 'Weight must be a non-negative number'}), 400

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Lưu dữ liệu vào database
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO sensor_data (temperature, humidity, weight, timestamp)
                     VALUES (?, ?, ?, ?)''',
                  (temperature, humidity, weight, current_time))
        conn.commit()
        
        logger.info(f"Sensor data recorded: Temp={temperature}, Humid={humidity}, Weight={weight}")
        
        # Gửi dữ liệu qua SocketIO
        socketio.emit('new_sensor_data', {
            'temperature': temperature,
            'humidity': humidity,
            'weight': weight,
            'timestamp': current_time
        })

        return jsonify({'status': 'success', 'message': 'Sensor data received and stored'})
    except Exception as e:
        logger.error(f"Error processing sensor data: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/sensor_data', methods=['GET'])
@login_required
def get_sensor_data_realtime():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
        row = c.fetchone()

        if row:
            return jsonify({
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'weight': row['weight'],
                'timestamp': row['timestamp']
            })
        logger.debug("No real-time sensor data available.")
        return jsonify({'status': 'error', 'message': 'No sensor data available'}), 404
    except Exception as e:
        logger.error(f"Error retrieving real-time sensor data: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/sensor_data_history', methods=['GET'])
@login_required
def get_sensor_data_history():
    """API lấy lịch sử dữ liệu cảm biến trong 24 giờ qua (lọc theo giờ)."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT * FROM sensor_data
                     WHERE timestamp >= datetime('now', '-24 hours')
                     ORDER BY timestamp DESC''')
        all_data = c.fetchall()

        sensor_data_history_filtered = []
        last_time = None
        for row in all_data:
            current_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
            if last_time is None or (last_time - current_time).total_seconds() >= 3600:
                sensor_data_history_filtered.append({
                    'temperature': row['temperature'],
                    'humidity': row['humidity'],
                    'weight': row['weight'],
                    'timestamp': row['timestamp']
                })
                last_time = current_time
            if len(sensor_data_history_filtered) >= 24:
                break
        logger.debug(f"Retrieved {len(sensor_data_history_filtered)} historical sensor data points.")
        return jsonify(sensor_data_history_filtered)
    except Exception as e:
        logger.error(f"Error retrieving sensor data history: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ----- API Routes: QR Code -----
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
            # Xử lý ảnh để nhận diện QR code
            logger.debug("Processing uploaded image for QR code detection using OpenCV")
            image_pil = Image.open(image_file)
            image_np = np.array(image_pil)
            
            # Xử lý ảnh dựa trên kênh màu
            if len(image_np.shape) == 3 and image_np.shape[2] == 4:
                image_np = cv2.cvtColor(image_np, cv2.COLOR_RGBA2RGB)
            elif len(image_np.shape) == 2:
                image_np = cv2.cvtColor(image_np, cv2.COLOR_GRAY2RGB)

            # Nhận diện QR code với nhiều phương pháp
            qr_data = None
            qr_detector = cv2.QRCodeDetector()
            
            # Thử với ảnh gốc
            data_opencv_orig, _, _ = qr_detector.detectAndDecode(image_np)
            if data_opencv_orig:
                qr_data = data_opencv_orig
                logger.info(f"QR code detected by OpenCV (original): {qr_data}")
            else:
                logger.debug("OpenCV failed on original image, attempting with grayscale and preprocessing")
                
                # Thử với các phương pháp tiền xử lý khác
                gray_image = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
                blurred_image = cv2.GaussianBlur(gray_image, (5, 5), 0)

                _, thresh_image_otsu = cv2.threshold(blurred_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                _, thresh_image_binary = cv2.threshold(gray_image, 127, 255, cv2.THRESH_BINARY)
                
                # Thử với ảnh xám
                data_opencv_gray, _, _ = qr_detector.detectAndDecode(gray_image)
                if data_opencv_gray:
                    qr_data = data_opencv_gray
                    logger.info(f"QR code detected by OpenCV (grayscale): {qr_data}")
                else:
                    # Thử với ngưỡng OTSU
                    data_opencv_otsu, _, _ = qr_detector.detectAndDecode(thresh_image_otsu)
                    if data_opencv_otsu:
                        qr_data = data_opencv_otsu
                        logger.info(f"QR code detected by OpenCV (OTSU threshold): {qr_data}")
                    else:
                        # Thử với ngưỡng nhị phân
                        data_opencv_binary, _, _ = qr_detector.detectAndDecode(thresh_image_binary)
                        if data_opencv_binary:
                            qr_data = data_opencv_binary
                            logger.info(f"QR code detected by OpenCV (Binary threshold): {qr_data}")

            if not qr_data:
                logger.warning("No QR code detected in image after all OpenCV attempts")
                return jsonify({'status': 'error', 'message': 'No QR code detected'}), 404
                
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = get_db_connection()
            c = conn.cursor()
            
            # Lưu hoặc cập nhật QR code vào database
            try:
                c.execute('''INSERT INTO QRdate (qr_code, name, timestamp)
                             VALUES (?, ?, ?)''',
                          (qr_data, 'QR Item', current_time))
                conn.commit()
                logger.info(f"QR code saved to QRdate: {qr_data}")
            except sqlite3.IntegrityError:
                c.execute('''UPDATE QRdate SET timestamp = ? WHERE qr_code = ?''',
                          (current_time, qr_data))
                conn.commit()
                logger.warning(f"QR code already exists in QRdate, timestamp updated: {qr_data}")

            # Tìm thông tin sản phẩm dựa trên QR code
            product_name = "Unknown Product" 
            c.execute('SELECT name FROM inventory WHERE qr_code = ? LIMIT 1', (qr_data,))
            inventory_item = c.fetchone()
            if inventory_item:
                product_name = inventory_item['name']
                logger.info(f"Found product name '{product_name}' for QR: {qr_data} in inventory.")
            else:
                logger.warning(f"No product found for QR: {qr_data} in inventory. Using default name.")

            # Lấy dữ liệu cân gần nhất
            latest_weight = 0.0 
            c.execute('SELECT weight FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
            sensor_row = c.fetchone()
            if sensor_row and sensor_row['weight'] is not None:
                latest_weight = sensor_row['weight']
                logger.info(f"Latest sensor weight: {latest_weight}")
            else:
                logger.warning("No latest weight data available from sensor_data. Setting to 0.")

            # Phát sự kiện WebSocket để cập nhật frontend
            logger.debug("Emitting WebSocket event for detected QR and associated data")
            socketio.emit('qr_scanned_data', {
                'qr_code': qr_data,
                'name': product_name,
                'weight': latest_weight,
                'timestamp': current_time 
            })

            # Trả về phản hồi JSON cho ESP32-CAM
            return jsonify({
                'status': 'success',
                'qr_code': qr_data,
                'name': product_name,
                'weight': latest_weight,
                'timestamp': current_time,
                'message': 'QR code detected and data sent to frontend.'
            }), 200

        except Exception as e:
            logger.error(f"Failed to process image or decode QR: {str(e)}", exc_info=True)
            return jsonify({'status': 'error', 'message': f'Error processing image or QR: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Unexpected error in upload_image route: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Internal server error: {str(e)}'}), 500

# ----- API Routes: Inventory Management -----
@app.route('/api/latest_data', methods=['GET'])
@login_required
def get_latest_data():
    """API lấy dữ liệu QR code và cảm biến mới nhất."""
    logger.debug("Fetching latest QR code and sensor data for display/refresh")
    conn = get_db_connection()
    c = conn.cursor()

    # Lấy QR code mới nhất
    c.execute('SELECT qr_code, name, timestamp FROM QRdate ORDER BY timestamp DESC LIMIT 1')
    qr_data_latest = c.fetchone()

    # Lấy dữ liệu cảm biến mới nhất
    c.execute('SELECT temperature, humidity, weight, timestamp FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
    sensor_data_latest = c.fetchone()

    response = {
        'qr_code': 'N/A',
        'name': 'N/A',
        'qr_timestamp': 'N/A',
        'temperature': 'N/A',
        'humidity': 'N/A',
        'sensor_weight': 0.0,
        'sensor_timestamp': 'N/A'
    }

    if qr_data_latest:
        response['qr_code'] = qr_data_latest['qr_code']
        response['name'] = qr_data_latest['name']
        response['qr_timestamp'] = qr_data_latest['timestamp']
        logger.debug(f"Latest QR code found: {qr_data_latest['qr_code']}")
    else:
        logger.debug("No QR data found in QRdate table.")

    if sensor_data_latest:
        response['temperature'] = sensor_data_latest['temperature']
        response['humidity'] = sensor_data_latest['humidity']
        response['sensor_weight'] = sensor_data_latest['weight'] if sensor_data_latest['weight'] is not None else 0.0
        response['sensor_timestamp'] = sensor_data_latest['timestamp']
        logger.debug(f"Latest sensor data found: Temp={sensor_data_latest['temperature']}, Humid={sensor_data_latest['humidity']}, Weight={response['sensor_weight']}")
    else:
        logger.debug("No sensor data found in sensor_data table.")
    
    return jsonify(response)

@app.route('/api/import_item', methods=['POST'])
@login_required
def import_item():
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        qr_code = data.get('qr_code')
        name = data.get('name')
        weight = data.get('weight')

        if not qr_code or not name:
            return jsonify({'status': 'error', 'message': 'QR code and name are required'}), 400
       
        if weight is not None and (not isinstance(weight, (int, float)) or weight < 0):
            return jsonify({'status': 'error', 'message': 'Weight must be a non-negative number or null'}), 400

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id, name, weight, quantity FROM inventory WHERE qr_code = ? LIMIT 1', (qr_code,))
        existing_item = c.fetchone()

        if existing_item:
            item_id = existing_item['id']
            new_quantity = existing_item['quantity'] + 1
            updated_name = name 
            existing_weight = existing_item['weight'] 

            c.execute('''UPDATE inventory SET quantity = ?, name = ?, timestamp = ?
                         WHERE id = ?''',
                      (new_quantity, updated_name, current_time, item_id))
            conn.commit()
            logger.info(f"Item quantity updated: qr_code={qr_code}, new_name={updated_name}, new_quantity={new_quantity}")
            return jsonify({
                'status': 'success',
                'message': f'Updated quantity for item with QR Code: {qr_code}. New quantity: {new_quantity}. Name updated to: {updated_name}',
                'qr_code': qr_code,
                'name': updated_name,
                'weight': existing_weight,
                'quantity': new_quantity
            })
        else:
            item_weight_to_insert = weight if weight is not None else 0.0

            c.execute('''INSERT INTO inventory (qr_code, name, weight, quantity, timestamp)
                         VALUES (?, ?, ?, 1, ?)''',
                      (qr_code, name, item_weight_to_insert, current_time))
            conn.commit()
            logger.info(f"Item imported (new): qr_code={qr_code}, name={name}, weight={item_weight_to_insert}")
            return jsonify({
                'status': 'success', 
                'message': f'Imported new item: {name} ({qr_code})',
                'qr_code': qr_code,
                'name': name,
                'weight': item_weight_to_insert,
                'quantity': 1
            })
    
    except Exception as e:
        logger.error(f"Error importing item: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/export_item', methods=['POST'])
@login_required
def export_item():
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400

        qr_code = data.get('qr_code')
        name = data.get('name')

        if not qr_code or not name:
            return jsonify({'status': 'error', 'message': 'QR code and name are required'}), 400

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT quantity FROM inventory WHERE qr_code = ? AND name = ?', (qr_code, name))
        row = c.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'No such product in inventory'}), 404

        quantity = row['quantity']
        if quantity > 1:
            c.execute('UPDATE inventory SET quantity = quantity - 1 WHERE qr_code = ? AND name = ?', (qr_code, name))
        else:
            c.execute('DELETE FROM inventory WHERE qr_code = ? AND name = ?', (qr_code, name))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Item exported successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
    """API lấy danh sách tồn kho."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM inventory ORDER BY timestamp DESC LIMIT 10')
        rows = c.fetchall()

        inventory = [
            {'id': row['id'], 'qr_code': row['qr_code'], 'name': row['name'],
             'weight': row['weight'], 'quantity': row['quantity'], 'timestamp': row['timestamp']}
            for row in rows
        ]
        logger.debug(f"Retrieved {len(inventory)} inventory items.")
        return jsonify(inventory)
    except Exception as e:
        logger.error(f"Error retrieving inventory: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)