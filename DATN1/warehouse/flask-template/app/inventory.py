import logging
from flask import Blueprint, jsonify, request
from instance.database import get_db_connection
from .utils import login_required
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)

logger = logging.getLogger(__name__)

@inventory_bp.route('/api/latest_data', methods=['GET'])
@login_required
def get_latest_data():
    logger.debug("Fetching latest QR code and sensor data for display/refresh")
    conn = get_db_connection()
    c = conn.cursor()

    c.execute('SELECT qr_code, name, timestamp FROM QRdate ORDER BY timestamp DESC LIMIT 1')
    qr_data_latest = c.fetchone()

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
        logger.debug(f"Latest sensor data found: Temperature={sensor_data_latest['temperature']}, Humidity={sensor_data_latest['humidity']}, Weight={response['sensor_weight']}")
    else:
        logger.debug("No sensor data found in sensor_data table.")
    
    return jsonify(response)

@inventory_bp.route('/api/import_item', methods=['POST'])
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

@inventory_bp.route('/api/export_item', methods=['POST'])
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
        logger.error(f"Error exporting item: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@inventory_bp.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
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