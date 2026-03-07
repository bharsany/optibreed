from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, current_user
from .models import User

auth_blueprint = Blueprint('auth', __name__)

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
