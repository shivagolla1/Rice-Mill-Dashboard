import os
import json
import hashlib
import secrets
from functools import wraps
from flask import session, request, redirect, url_for, jsonify, current_app

USERS_FILE_NAME = 'users.json'

def get_users_path():
    try:
        import sys
        if 'app' in sys.modules:
            base = sys.modules['app'].EXE_DIR
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(base, 'data')
    if os.path.isdir(data_dir):
        return os.path.join(data_dir, USERS_FILE_NAME)
    return os.path.join(base, USERS_FILE_NAME)


def hash_password(password: str, salt: str = None) -> str:
    """Hash password using PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, hashed_str: str) -> bool:
    """Verify password against salt$hash string."""
    try:
        salt, key_hex = hashed_str.split('$')
        computed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return secrets.compare_digest(computed.hex(), key_hex)
    except Exception:
        return False

def load_users():
    p = get_users_path()
    if not os.path.exists(p):
        users = init_default_users()
    else:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                users = json.load(f)
        except Exception:
            users = init_default_users()

    # Automatically sync admin/staff passwords from environment variables if set
    env_admin_pass = os.environ.get('ADMIN_PASSWORD', '').strip()
    env_staff_pass = os.environ.get('STAFF_PASSWORD', '').strip()
    updated = False

    if env_admin_pass and 'admin' in users:
        if not verify_password(env_admin_pass, users['admin']['password_hash']):
            users['admin']['password_hash'] = hash_password(env_admin_pass)
            updated = True

    if env_staff_pass and 'staff' in users:
        if not verify_password(env_staff_pass, users['staff']['password_hash']):
            users['staff']['password_hash'] = hash_password(env_staff_pass)
            updated = True

    if updated:
        save_users(users)

    return users


def save_users(users_dict):
    p = get_users_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(users_dict, f, indent=2)

def init_default_users():
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
    staff_pass = os.environ.get('STAFF_PASSWORD', 'staff123')
    
    users = {
        'admin': {
            'username': 'admin',
            'password_hash': hash_password(admin_pass),
            'role': 'admin',
            'name': 'Administrator'
        },
        'staff': {
            'username': 'staff',
            'password_hash': hash_password(staff_pass),
            'role': 'staff',
            'name': 'Mill Staff'
        }
    }
    save_users(users)
    return users

def authenticate_user(username, password):
    users = load_users()
    username = username.strip().lower()
    if username in users:
        u = users[username]
        if verify_password(password, u['password_hash']):
            return u
    return None

def create_user(username, password, role='staff', name=None):
    users = load_users()
    username = username.strip().lower()
    if username in users:
        return False, "User already exists"
    if role not in ('admin', 'staff'):
        return False, "Invalid role"
        
    users[username] = {
        'username': username,
        'password_hash': hash_password(password),
        'role': role,
        'name': name or username.capitalize()
    }
    save_users(users)
    return True, "User created successfully"

def get_current_user():
    username = session.get('user')
    if not username:
        return None
    users = load_users()
    return users.get(username)

def login_required(role=None):
    """
    Decorator for route functions to enforce login.
    Optional role parameter ('admin' or 'staff').
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if authentication is enabled in environment/config
            auth_enabled = os.environ.get('ENABLE_AUTH', 'True').strip().lower() in ('true', '1', 'yes')
            if not auth_enabled:
                return f(*args, **kwargs)
                
            user = get_current_user()
            if not user:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'unauthorized', 'message': 'Authentication required'}), 401
                return redirect(url_for('login_page', next=request.url))
                
            if role == 'admin' and user.get('role') != 'admin':
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'forbidden', 'message': 'Admin access required'}), 403
                return render_template('login.html', error="Admin privileges required for this page."), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
