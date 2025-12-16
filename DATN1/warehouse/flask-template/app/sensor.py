import logging
from flask import Blueprint, jsonify, request
from instance.database import get_db_connection
from .utils import login_required
from datetime import datetime, timedelta
from app import socketio 
sensor_bp = Blueprint('sensor', __name__)

logger = logging.getLogger(__name__)

@sensor_bp.route('/api/sensor', methods=['POST'])
def sensor_data_api():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data provided for sensor_data_api")
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
        
        logger.info(f"Sensor data recorded: Temperature={temperature}, Humidity={humidity}, Weight={weight}")
        
        socketio.emit('new_sensor_data', {
            'temperature': temperature,
            'humidity': humidity,
            'weight': weight,
            'timestamp': current_time
        }, namespace='/')

        return jsonify({'status': 'success', 'message': 'Sensor data received and stored'})
    except Exception as e:
        logger.error(f"Error processing sensor data: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@sensor_bp.route('/api/sensor_data', methods=['GET'])
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


@sensor_bp.route('/api/sensor_data_history', methods=['GET'])
@login_required
def get_sensor_data_history():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=1)
        c.execute('''
            SELECT * FROM sensor_data
            WHERE timestamp <= ?
            ORDER BY timestamp DESC
        ''', (cutoff_time.strftime('%Y-%m-%d %H:%M:%S'),))
        filtered_rows = c.fetchall()

        historical = []
        last_time = None
        for row in filtered_rows:
            current_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')

            if last_time is None or (last_time - current_time).total_seconds() >= 3600:
                historical.append({
                    'temperature': row['temperature'],
                    'humidity': row['humidity'],
                    'weight': row['weight'],
                    'timestamp': row['timestamp']
                })
                last_time = current_time

            if len(historical) >= 10:
                break

        logger.info(f"Lấy được {len(historical)} bản ghi cảm biến lịch sử.")
        try:
            return jsonify(historical)
        except ConnectionResetError:
            logger.debug("Client disconnected trước khi nhận dữ liệu sensor history.")
            return ("", 204)

    except Exception as e:
        logger.error(f"Error retrieving sensor data history: {str(e)}", exc_info=True)
        try:
            return jsonify({'status': 'error', 'message': str(e)}), 500
        except ConnectionResetError:
            return ("", 204)
        