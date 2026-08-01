import os
import json
import hashlib
import secrets
from functools import wraps
from datetime import datetime
from flask import session, request, redirect, url_for, jsonify, current_app, render_template


USERS_FILE_NAME = 'users.json'

def get_current_user():
    if 'user' in session:
        return session['user']
    return None

def get_tenant_users_path(tenant_id="client_default"):

    from tenants import get_tenant_dir
    tenant_dir = get_tenant_dir(tenant_id)
    return os.path.join(tenant_dir, USERS_FILE_NAME)

def hash_password(password: str, salt: str = None) -> str:
    """Hash password using PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, hashed_str: str) -> bool:
    """Verify password against salt$hash string."""
    try:
        salt, key_hex = hashed_str.split('$')
        computed = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), salt.encode('utf-8'), 100000)
        return secrets.compare_digest(computed.hex(), key_hex)
    except Exception:
        return False

def init_tenant_users(tenant_id="client_default", admin_pass=None, staff_pass=None):
    if not admin_pass:
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin2486').strip()
    if not staff_pass:
        staff_pass = os.environ.get('STAFF_PASSWORD', 'staff123').strip()

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
    save_tenant_users(tenant_id, users)
    return users

def load_tenant_users(tenant_id="client_default"):
    p = get_tenant_users_path(tenant_id)
    if not os.path.exists(p):
        return init_tenant_users(tenant_id)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            users = json.load(f)
            if not users:
                return init_tenant_users(tenant_id)
            return users
    except Exception:
        return init_tenant_users(tenant_id)

def save_tenant_users(tenant_id, users_dict):
    p = get_tenant_users_path(tenant_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(users_dict, f, indent=2)

def authenticate_user(company_code, username, password):
    from tenants import get_tenant_by_code
    
    if not company_code or not username or not password:
        return None, "Company Code, Username, and Password are required."

    tenant = get_tenant_by_code(company_code)
    if not tenant:
        return None, f"Company Code '{company_code.strip().upper()}' not found!"

    # Check Tenant Subscription Expiry & Status
    status = tenant.get('status', 'ACTIVE').upper()
    if status in ('EXPIRED', 'SUSPENDED'):
        return None, f"Subscription for {tenant.get('company_name')} is {status}. Please contact support."

    expiry_str = tenant.get('expiry_date')
    if expiry_str:
        try:
            exp_date = datetime.strptime(expiry_str, "%Y-%m-%d")
            if exp_date < datetime.now():
                return None, f"Subscription for {tenant.get('company_name')} expired on {expiry_str}. Please renew."
        except Exception:
            pass

    tenant_id = tenant.get('tenant_id')
    users = load_tenant_users(tenant_id)
    username_clean = username.strip().lower()

    if username_clean in users:
        u = users[username_clean]
        if verify_password(password, u['password_hash']):
            user_data = dict(u)
            user_data['tenant_id'] = tenant_id
            user_data['company_code'] = tenant.get('company_code')
            user_data['company_name'] = tenant.get('company_name')
            return user_data, None

    return None, "Invalid username or password for this company code."

def change_user_password(tenant_id, username, old_password, new_password):
    users = load_tenant_users(tenant_id)
    username_clean = username.strip().lower()
    if username_clean not in users:
        return False, "User not found."
    
    u = users[username_clean]
    if not verify_password(old_password, u['password_hash']):
        return False, "Current password is incorrect."

    u['password_hash'] = hash_password(new_password)
    save_tenant_users(tenant_id, users)
    return True, "Password changed successfully."

def reset_password_with_license_key(company_code, license_key, username, new_password):
    from tenants import get_tenant_by_code
    tenant = get_tenant_by_code(company_code)
    if not tenant:
        return False, f"Company Code '{company_code}' not found."

    # Validate License Key
    expected_key = tenant.get('license_key', '').strip()
    if not license_key or license_key.strip() != expected_key:
        return False, "Invalid License Key verification failed!"

    tenant_id = tenant.get('tenant_id')
    users = load_tenant_users(tenant_id)
    username_clean = username.strip().lower()

    if username_clean not in users:
        # Create user if admin
        users[username_clean] = {
            'username': username_clean,
            'password_hash': hash_password(new_password),
            'role': 'admin' if username_clean == 'admin' else 'staff',
            'name': username_clean.capitalize()
        }
    else:
        users[username_clean]['password_hash'] = hash_password(new_password)

    save_tenant_users(tenant_id, users)
    return True, f"Password for '{username_clean}' reset successfully. You may now log in."

def create_tenant_user(tenant_id, username, password, role='staff', name=None):
    users = load_tenant_users(tenant_id)
    username_clean = username.strip().lower()
    if username_clean in users:
        return False, f"User '{username_clean}' already exists."

    users[username_clean] = {
        'username': username_clean,
        'password_hash': hash_password(password),
        'role': role,
        'name': name or username_clean.capitalize()
    }
    save_tenant_users(tenant_id, users)
    return True, f"User '{username_clean}' created successfully."

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            enable_auth = os.environ.get('ENABLE_AUTH', 'True').strip().lower() in ('true', '1', 'yes')
            if not enable_auth:
                return f(*args, **kwargs)
            
            is_super = session.get('is_super_admin', False) or (isinstance(session.get('user'), dict) and session.get('user', {}).get('role') == 'super_admin')

            if role == 'super_admin':
                if not is_super:
                    if request.path.startswith('/api/'):
                        return jsonify({'status': 'error', 'message': 'Super-Admin authorization required'}), 403
                    return render_template('super_admin_login.html')
                return f(*args, **kwargs)

            if 'user' not in session and not is_super:
                if request.path.startswith('/api/'):
                    return jsonify({'status': 'error', 'message': 'Authentication required'}), 401
                return redirect(url_for('login_page', next=request.url))

            user_role = session.get('user', {}).get('role') if isinstance(session.get('user'), dict) else ''
            if role and user_role != role and not is_super:
                if request.path.startswith('/api/'):
                    return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
                try:
                    return render_template('403.html', message="Admin access required"), 403
                except Exception:
                    return "<h3 style='font-family:sans-serif; text-align:center; margin-top:50px;'>403 Forbidden: Admin access required</h3>", 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator

