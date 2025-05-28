import logging
import cv2
import numpy as np
from flask import Blueprint, request, jsonify
from instance.database import get_db_connection
from datetime import datetime
from PIL import Image
from app import socketio 
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
import sqlite3 

qr_bp = Blueprint('qr', __name__)

logger = logging.getLogger(__name__)

@qr_bp.route('/upload_image', methods=['POST'])
def upload_image():
    try:
        if not request.content_type.startswith('multipart/form-data'):
            logger.error("Invalid content type: %s", request.content_type)
            return jsonify({'status': 'error', 'message': 'Content-Type must be multipart/form-data'}), 400

        if 'image' not in request.files:
            logger.error("No 'image' field in request.files")
            return jsonify({'status': 'error', 'message': 'No image field provided'}), 400

        image_file = request.files['image']
        if image_file.filename == '':
            logger.error("Empty image filename")
            return jsonify({'status': 'error', 'message': 'No image selected'}), 400

        image_file.seek(0)

        try:
            logger.debug("Processing uploaded image for QR code detection using OpenCV")
            image_pil = Image.open(image_file)
            image_np = np.array(image_pil)
            
            if len(image_np.shape) == 3 and image_np.shape[2] == 4:
                image_np = cv2.cvtColor(image_np, cv2.COLOR_RGBA2RGB)
            elif len(image_np.shape) == 2:
                image_np = cv2.cvtColor(image_np, cv2.COLOR_GRAY2RGB)

            qr_data = None
            qr_detector = cv2.QRCodeDetector()
            
            data_opencv_orig, _, _ = qr_detector.detectAndDecode(image_np)
            if data_opencv_orig:
                qr_data = data_opencv_orig
                logger.info(f"QR code detected by OpenCV (original): {qr_data}")
            else:
                logger.debug("OpenCV failed on original image, attempting with grayscale and preprocessing")
                
                gray_image = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
                blurred_image = cv2.GaussianBlur(gray_image, (5, 5), 0)

                _, thresh_image_otsu = cv2.threshold(blurred_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                _, thresh_image_binary = cv2.threshold(gray_image, 127, 255, cv2.THRESH_BINARY)
                
                data_opencv_gray, _, _ = qr_detector.detectAndDecode(gray_image)
                if data_opencv_gray:
                    qr_data = data_opencv_gray
                    logger.info(f"QR code detected by OpenCV (grayscale): {qr_data}")
                else:
                    data_opencv_otsu, _, _ = qr_detector.detectAndDecode(thresh_image_otsu)
                    if data_opencv_otsu:
                        qr_data = data_opencv_otsu
                        logger.info(f"QR code detected by OpenCV (OTSU threshold): {qr_data}")
                    else:
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

            product_name = "Unknown Product"
            c.execute('SELECT name FROM inventory WHERE qr_code = ? LIMIT 1', (qr_data,))
            inventory_item = c.fetchone()
            if inventory_item:
                product_name = inventory_item['name']
                logger.info(f"Found product name '{product_name}' for QR: {qr_data} in inventory.")
            else:
                logger.warning(f"No product found for QR: {qr_data} in inventory. Using default name.")

            latest_weight = 0.0
            c.execute('SELECT weight FROM sensor_data ORDER BY timestamp DESC LIMIT 1')
            sensor_row = c.fetchone()
            if sensor_row and sensor_row['weight'] is not None:
                latest_weight = sensor_row['weight']
                logger.info(f"Latest sensor weight: {latest_weight}")

            logger.debug("Emitting WebSocket event for detected QR and associated data")
            socketio.emit('qr_scanned_data', {
                'qr_code': qr_data,
                'name': product_name,
                'weight': latest_weight,
                'timestamp': current_time
            }, namespace='/')

            return jsonify({
                'status': 'success',
                'qr_code': qr_data,
                'name': product_name,
                'weight': latest_weight,
                'timestamp': current_time,
                'message': 'QR code detected and data sent to frontend.'
            }), 200

        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error processing image or QR: {str(e)}'}), 500

    except BadRequest as e:
        return jsonify({'status': 'error', 'message': 'Invalid request format'}), 400
    except RequestEntityTooLarge:
        return jsonify({'status': 'error', 'message': 'Image size exceeds limit'}), 413
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Internal server error: {str(e)}'}), 500