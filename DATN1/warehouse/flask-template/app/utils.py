from flask import flash, redirect, url_for, session

def login_required(f):
    """Decorator to require user login before accessing a route."""
    def wrap(*args, **kwargs):
        if not session.get('flag'):
            flash("Please log in to access this page.")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap