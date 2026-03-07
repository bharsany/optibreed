import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv

# Initialize extensions globally
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Kérjük, jelentkezzen be az oldal eléréséhez.'


def create_app():
    app = Flask(__name__)
    load_dotenv()

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB
    
    # Configure SQLite Database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///../optibreed.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)

    # Late import of models to avoid circular dependencies
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Initialize DB schema and create a default admin if non-existent
    with app.app_context():
        db.create_all()
        # Seed default admin user
        if not User.query.filter_by(is_admin=True).first():
            default_admin = User(
                name='Rendszergazda',
                email='admin@optibreed.com',
                company='Adminisztráció',
                is_admin=True
            )
            default_admin.set_password('admin123')
            db.session.add(default_admin)
            db.session.commit()
            print("Default admin created: admin@optibreed.com / admin123")

    # In-memory session store
    app.sessions = {}

    # Register blueprints
    from .routes import main_blueprint
    from .auth import auth_blueprint
    from .admin import admin_blueprint
    
    app.register_blueprint(main_blueprint)
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    app.register_blueprint(admin_blueprint, url_prefix='/admin')

    return app
