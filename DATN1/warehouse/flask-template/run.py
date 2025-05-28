import logging
from app import create_app
logging.basicConfig(level=logging.DEBUG)
     
app, socketio = create_app()
     
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)