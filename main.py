from flask import Flask
import os

app = Flask(__name__, template_folder='app/templates')

# Hardcoded secret key for session management
app.config['SECRET_KEY'] = 'a-temporary-but-very-secret-key-that-will-be-changed-later'

# Register the blueprint from the pedigree sub-package
from app.pedigree.main import bp as pedigree_bp
app.register_blueprint(pedigree_bp)

@app.route('/')
def index():
    return "Welcome to OptiBreed!"
