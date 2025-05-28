import os
from flask import Flask
from flask_socketio import SocketIO
from instance.database import init_db, close_db

# Initialize SocketIO at module level
socketio = SocketIO(cors_allowed_origins="*")

def create_app():
    """Initialize the Flask application and related components."""
    app = Flask(__name__, 
                template_folder='../templates',  
                static_folder='../static')
    
    app.config.from_object('config.Config')
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
    

    socketio.init_app(app)

    app.teardown_appcontext(close_db)
    
    with app.app_context():
        init_db()
    from .auth import auth_bp
    from .routes import main_bp
    from .sensor import sensor_bp
    from .qr import qr_bp
    from .inventory import inventory_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(sensor_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(inventory_bp)
    
    return app, socketio