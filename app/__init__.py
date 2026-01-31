import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

    # Register blueprints here
    from .main import bp as main_bp
    app.register_blueprint(main_bp)

    from .pedigree.main import bp as pedigree_bp
    app.register_blueprint(pedigree_bp)

    return app
