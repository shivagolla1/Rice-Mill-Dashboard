import os
import json
import secrets
import string
import time
from datetime import datetime, timedelta

TENANTS_FILE_NAME = 'tenants.json'

def get_base_data_dir():
    # Use BASE from app if defined, or file directory
    try:
        import sys
        if 'App.app' in sys.modules:
            base = sys.modules['App.app'].BASE
        elif 'app' in sys.modules:
            base = sys.modules['app'].BASE
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))

    # Check for DATA_DIR environment variable
    env_dir = os.environ.get('DATA_DIR', '').strip()
    if env_dir:
        return env_dir

    data_dir = os.path.join(base, 'data')
    if not os.path.exists(data_dir):
        # Fallback for Railway root environment
        root_data = '/app/data'
        if os.path.isdir('/app'):
            return root_data
    return data_dir

def get_tenants_file_path():
    data_dir = get_base_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, TENANTS_FILE_NAME)

def get_tenant_dir(tenant_id):
    data_dir = get_base_data_dir()
    tenant_dir = os.path.join(data_dir, 'tenants', tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    return tenant_dir

def generate_key(prefix="RM", length=4):
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(length))
    part2 = ''.join(secrets.choice(string.digits) for _ in range(4))
    return f"{prefix}-{part1}-{part2}"

def init_default_tenants():
    # Migration helper: ensure primary single-tenant client (SGRI) is registered
    primary_key = os.environ.get('SYNC_SECRET_TOKEN', 'RiceMillSyncSecretToken2026!').strip()
    primary_enc = os.environ.get('ENCRYPTION_KEY', 'RiceMillDashboardDefaultEncryptionKey2026!').strip()

    tenants = {
        "RM-SGRI-2026": {
            "tenant_id": "client_sgri",
            "company_name": "Sri Ganesh Rice Mill",
            "company_code": "SGRI",
            "license_key": "RM-SGRI-2026",
            "secret_token": primary_key,
            "encryption_key": primary_enc,
            "status": "ACTIVE",
            "expiry_date": "2030-12-31",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "show_stocks": False,
            "show_bi_reports": False
        }
    }
    save_tenants(tenants)
    return tenants

def load_tenants():
    p = get_tenants_file_path()
    if not os.path.exists(p):
        return init_default_tenants()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not data:
                return init_default_tenants()
            return data
    except Exception:
        return init_default_tenants()

def save_tenants(tenants_dict):
    p = get_tenants_file_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(tenants_dict, f, indent=2)

def get_tenant_by_code(company_code):
    if not company_code:
        return None
    code_clean = company_code.strip().upper()
    tenants = load_tenants()
    for t in tenants.values():
        if t.get('company_code', '').upper() == code_clean:
            return t
    return None

def get_tenant_by_key(license_key):
    if not license_key:
        return None
    key_clean = license_key.strip()
    tenants = load_tenants()
    if key_clean in tenants:
        return tenants[key_clean]
    for t in tenants.values():
        if t.get('secret_token') == key_clean or t.get('license_key') == key_clean:
            return t
    return None

def get_tenant_by_id(tenant_id):
    if not tenant_id:
        return None
    tenants = load_tenants()
    for t in tenants.values():
        if t.get('tenant_id') == tenant_id:
            return t
    return None

def create_tenant(company_name, company_code, admin_password, months=12, show_stocks=False, show_bi_reports=False):
    company_code = company_code.strip().upper()
    tenants = load_tenants()

    # Check if company code already exists
    if get_tenant_by_code(company_code):
        return False, f"Company Code '{company_code}' already exists!", None

    tenant_id = f"client_{company_code.lower()}"
    license_key = generate_key(prefix=f"RM-{company_code[:4]}")
    secret_token = f"Token_{company_code}_{secrets.token_hex(4)}"
    encryption_key = f"EncKey_{company_code}_{secrets.token_hex(8)}"
    
    expiry_dt = datetime.now() + timedelta(days=30 * months)
    
    tenant_info = {
        "tenant_id": tenant_id,
        "company_name": company_name.strip(),
        "company_code": company_code,
        "license_key": license_key,
        "secret_token": secret_token,
        "encryption_key": encryption_key,
        "status": "ACTIVE",
        "expiry_date": expiry_dt.strftime("%Y-%m-%d"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "show_stocks": bool(show_stocks),
        "show_bi_reports": bool(show_bi_reports)
    }

    tenants[license_key] = tenant_info
    save_tenants(tenants)

    # Initialize tenant user account
    from auth import init_tenant_users
    init_tenant_users(tenant_id, admin_password)

    return True, "Tenant created successfully", tenant_info

def update_tenant_status(license_key, status=None, expiry_date=None, show_stocks=None, show_bi_reports=None):
    tenants = load_tenants()
    tenant = tenants.get(license_key)
    if not tenant:
        # Try finding by tenant_id
        for k, t in tenants.items():
            if t.get('tenant_id') == license_key:
                tenant = t
                license_key = k
                break
    if not tenant:
        return False, "Tenant not found"

    if status:
        tenant['status'] = status.upper()
    if expiry_date:
        tenant['expiry_date'] = expiry_date
    if show_stocks is not None:
        tenant['show_stocks'] = bool(show_stocks)
    if show_bi_reports is not None:
        tenant['show_bi_reports'] = bool(show_bi_reports)

    tenants[license_key] = tenant
    save_tenants(tenants)
    return True, "Tenant updated successfully"

def update_tenant_company_name(license_key, new_company_name):
    if not new_company_name or not new_company_name.strip():
        return False, "Company Name cannot be empty"
    tenants = load_tenants()
    tenant = tenants.get(license_key)
    if not tenant:
        for k, t in tenants.items():
            if t.get('tenant_id') == license_key or t.get('company_code') == license_key:
                tenant = t
                license_key = k
                break
    if not tenant:
        return False, "Tenant not found"

    tenant['company_name'] = new_company_name.strip()
    tenants[license_key] = tenant
    save_tenants(tenants)
    return True, "Company Name updated successfully"

