from flask import Blueprint, request, render_template, redirect, url_for, flash, session
from instance.database import get_db_connection
from .utils import login_required
import sqlite3

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
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
            session['user_id'] = user_id  # Store user_id in session
            return redirect(url_for('main.index'))
        flash("Login failed.")
        return redirect(url_for('auth.login'))
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form.get('id')
        user_pw = request.form.get('pw')
        user_tel = request.form.get('tel')
        user_job_num = request.form.get('job_num')

        if not user_id or not user_pw or not user_tel or not user_job_num:
            flash("All fields are required!")
            return redirect(url_for('auth.register'))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO admin (admin_id, password, tel, job_num) VALUES (?, ?, ?, ?)",
                        (user_id, user_pw, user_tel, user_job_num))
            conn.commit()
            flash("Registration successful! Please log in.")
            return redirect(url_for('auth.login'))
        except sqlite3.IntegrityError:
            flash("Registration failed. User ID may already exist.")
            return redirect(url_for('auth.register'))
    return render_template('register.html')

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session.get('user_id')
    if not user_id:
        flash("User not logged in.")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT admin_id, tel, job_num FROM admin WHERE admin_id = ?", (user_id,))
    user = cur.fetchone()

    if not user:
        flash("User not found.")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        new_password = request.form.get('pw')
        new_tel = request.form.get('tel')
        new_job_num = request.form.get('job_num')

        if not new_tel or not new_job_num:
            flash("Phone number and job number are required!")
            return redirect(url_for('auth.profile'))

        try:
            update_query = "UPDATE admin SET tel = ?, job_num = ?"
            params = [new_tel, new_job_num]

            if new_password:
                update_query += ", password = ?"
                params.append(new_password)

            update_query += " WHERE admin_id = ?"
            params.append(user_id)

            cur.execute(update_query, params)
            conn.commit()
            flash("Profile updated successfully!")
            return redirect(url_for('auth.profile'))
        except sqlite3.Error as e:
            flash(f"Failed to update profile: {str(e)}")
            return redirect(url_for('auth.profile'))

    return render_template('profile.html', user=user)

@auth_bp.route('/logout')
def logout():
    session.pop('flag', None)
    session.pop('user_id', None)
    flash("You have been logged out.")
    return redirect(url_for('auth.login'))