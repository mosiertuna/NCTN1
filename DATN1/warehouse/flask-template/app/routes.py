from flask import Blueprint, render_template
from instance.database import get_db_connection
from .utils import login_required
from datetime import datetime

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()
    
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

    inventory = conn.execute('SELECT * FROM inventory ORDER BY timestamp DESC').fetchall()
    return render_template('index.html', sensor_data=sensor_data_filtered, inventory=inventory)