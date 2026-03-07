from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from . import db
from .models import User

admin_blueprint = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Ehhez az oldalhoz adminisztrátori jogosultság szükséges.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_blueprint.route('/users')
@login_required
@admin_required
def list_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@admin_blueprint.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    name = request.form.get('name')
    email = request.form.get('email')
    company = request.form.get('company')
    password = request.form.get('password')
    is_admin = True if request.form.get('is_admin') == 'on' else False

    # Check if email already exists
    if User.query.filter_by(email=email).first():
        flash('Ezzel az email címmel már regisztráltak egy felhasználót.', 'danger')
        return redirect(url_for('admin.list_users'))

    new_user = User(name=name, email=email, company=company, is_admin=is_admin)
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()
    
    flash(f'{name} sikeresen hozzáadva!', 'success')
    return redirect(url_for('admin.list_users'))

@admin_blueprint.route('/users/update/<int:id>', methods=['POST'])
@login_required
@admin_required
def update_user(id):
    user = db.session.get(User, id)
    if not user:
        flash('A felhasználó nem található.', 'danger')
        return redirect(url_for('admin.list_users'))

    user.name = request.form.get('name')
    new_email = request.form.get('email')
    user.company = request.form.get('company')
    user.is_admin = True if request.form.get('is_admin') == 'on' else False
    
    # Check email duplicate only if the email changed
    if new_email != user.email:
        if User.query.filter_by(email=new_email).first():
            flash('Ezzel az email címmel már regisztráltak egy felhasználót.', 'danger')
            return redirect(url_for('admin.list_users'))
        user.email = new_email

    password = request.form.get('password')
    if password:  # Only update if a new password is provided
        user.set_password(password)

    db.session.commit()
    flash(f'{user.name} adatai frissítve!', 'success')
    return redirect(url_for('admin.list_users'))

@admin_blueprint.route('/users/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    user = db.session.get(User, id)
    if not user:
        flash('A felhasználó nem található.', 'danger')
        return redirect(url_for('admin.list_users'))
        
    if user.id == current_user.id:
        flash('Saját magadat nem törölheted!', 'danger')
        return redirect(url_for('admin.list_users'))

    db.session.delete(user)
    db.session.commit()
    flash(f'{user.name} felhasználó törölve!', 'success')
    return redirect(url_for('admin.list_users'))
