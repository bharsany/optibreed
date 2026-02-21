import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB

    # In-memory session store
    app.sessions = {}

    # Register blueprints
    from .routes import main_blueprint
    app.register_blueprint(main_blueprint)

    return app
