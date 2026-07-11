from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, current_user
from .models import User
from . import db

auth_blueprint = Blueprint('auth', __name__)

@auth_blueprint.route('/setup', methods=['GET', 'POST'])
def setup():
    from . import is_setup_required
    if not is_setup_required(current_app):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        company = request.form.get('company')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not name or not email or not password:
            flash('Minden kötelező mezőt ki kell tölteni!', 'danger')
            return redirect(url_for('auth.setup'))

        if password != confirm_password:
            flash('A két jelszó nem egyezik meg!', 'danger')
            return redirect(url_for('auth.setup'))

        # Dynamically create database tables since the database might not exist yet
        try:
            db.create_all()
        except Exception as e:
            current_app.logger.error(f"Error during database initialization: {e}")
            flash('Hiba történt az adatbázis inicializálása során!', 'danger')
            return redirect(url_for('auth.setup'))

        # Safety check to prevent double setup
        if User.query.filter_by(is_admin=True).first():
            current_app.config['SETUP_COMPLETE'] = True
            flash('A rendszer már be van állítva!', 'warning')
            return redirect(url_for('auth.login'))

        # Create new admin user
        new_admin = User(
            name=name,
            email=email,
            company=company,
            is_admin=True
        )
        new_admin.set_password(password)

        try:
            db.session.add(new_admin)
            db.session.commit()
            current_app.config['SETUP_COMPLETE'] = True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating admin user: {e}")
            flash('Hiba történt a felhasználó létrehozása során!', 'danger')
            return redirect(url_for('auth.setup'))

        # Log in the new admin user
        login_user(new_admin)
        session['boot_id'] = current_app.boot_id
        flash('Az adminisztrációs fiók sikeresen létrejött!', 'success')
        return redirect(url_for('main.index'))

    return render_template('setup.html')

@auth_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash('Helytelen email vagy jelszó. Kérjük, próbálja újra.', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=remember)
        # Stamp the current server boot ID so stale sessions from old deploys are rejected
        session['boot_id'] = current_app.boot_id
        
        # Determine next page
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('main.index')
            
        return redirect(next_page)

    return render_template('login.html')

@auth_blueprint.route('/logout')
def logout():
    session_id = session.get('user_session_id')
    if session_id and hasattr(current_app, 'sessions') and session_id in current_app.sessions:
        del current_app.sessions[session_id]
        current_app.logger.info(f"Cleared in-memory data for session {session_id} on logout.")
    
    session.clear()
    logout_user()
    return redirect(url_for('auth.login'))
