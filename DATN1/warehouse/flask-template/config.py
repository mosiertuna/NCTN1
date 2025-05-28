import os
import secrets
from datetime import timedelta

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(16))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=10)