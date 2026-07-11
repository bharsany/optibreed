import os
import uuid
from flask import Flask, session, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, logout_user, current_user
from dotenv import load_dotenv

# Initialize extensions globally
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Kérjük, jelentkezzen be az oldal eléréséhez.'


def is_setup_required(app):
    """Check if the system requires first-time admin setup."""
    if app.config.get('SETUP_COMPLETE'):
        return False
    
    db_path = app.config.get('DB_PATH')
    if not db_path or not os.path.exists(db_path):
        return True
        
    try:
        from .models import User
        with app.app_context():
            admin_exists = User.query.filter_by(is_admin=True).first() is not None
            if admin_exists:
                app.config['SETUP_COMPLETE'] = True
                return False
            return True
    except Exception:
        return True


def create_app():
    app = Flask(__name__)
    load_dotenv()

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB
    
    # Configure SQLite Database
    import sys
    if getattr(sys, 'frozen', False):
        # Running as a compiled executable, database goes next to the .exe
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as standard script, database goes to parent directory of app/
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    db_path = os.path.join(base_dir, 'optibreed.db')
    app.config['DB_PATH'] = db_path
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)

    # Late import of models to avoid circular dependencies
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        if is_setup_required(app):
            return None
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # We do not call db.create_all() at boot time anymore to allow clean on-demand creation.
    # We check if setup is already complete and cache it if so.
    try:
        if os.path.exists(db_path):
            with app.app_context():
                if User.query.filter_by(is_admin=True).first() is not None:
                    app.config['SETUP_COMPLETE'] = True
    except Exception:
        pass

    # In-memory session store
    app.sessions = {}

    # Generate a unique boot ID – changes on every server restart/redeploy.
    # Any browser session that carries a different boot_id will be logged out.
    app.boot_id = str(uuid.uuid4())

    @app.before_request
    def check_setup():
        """Redirect to setup route if database is not set up."""
        # Allow requests to the setup endpoint, static files, and logout
        if request.endpoint in ('auth.setup', 'static', 'auth.logout'):
            return
            
        if is_setup_required(app):
            return redirect(url_for('auth.setup'))

    @app.before_request
    def enforce_boot_id():
        """Log out users whose session predates the current server boot."""
        if is_setup_required(app):
            return
        if current_user.is_authenticated:
            if session.get('boot_id') != app.boot_id:
                logout_user()
                session.clear()
                return  # Flask will handle redirect to login via login_required

    # Register blueprints
    from .routes import main_blueprint
    from .auth import auth_blueprint
    from .admin import admin_blueprint
    
    app.register_blueprint(main_blueprint)
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    app.register_blueprint(admin_blueprint, url_prefix='/admin')

    return app
