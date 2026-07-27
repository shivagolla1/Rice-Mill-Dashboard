import os
import json
import hmac
import hashlib
from datetime import datetime, date as dobj

LICENSE_SECRET = b"SapthagiriRiceMillSecretSaltValue2026!"

def verify_license_signature(license_dict):
    sig = license_dict.get("signature", "")
    name = license_dict.get("industry_name", "")
    expiry = license_dict.get("expiry_date", "")
    msg = f"{name}|{expiry}".encode("utf-8")
    computed_sig = hmac.new(LICENSE_SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_sig, sig)

def check_license(exe_dir, industry_name):
    """
    Checks the license status.
    Returns: (is_licensed, error_message)
    """
    p = os.path.join(exe_dir, 'license.key')
    if not os.path.exists(p):
        return False, "License key file (license.key) is missing."
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not verify_license_signature(data):
            return False, "Invalid license key signature."
        
        lic_name = data.get('industry_name', '').strip()
        
        # Alphanumeric case-insensitive normalization to tolerate spelling spacing/case mismatch
        def clean_name(s):
            return ''.join(c.lower() for c in s if c.isalnum())
            
        if clean_name(lic_name) != clean_name(industry_name):
            return False, f"License registered for '{lic_name}', but app is configured as '{industry_name}'."
            
        expiry_str = data.get('expiry_date', '')
        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        if dobj.today() > expiry_dt:
            return False, f"License expired on {expiry_str}."
            
        return True, ""
    except Exception as e:
        return False, f"Error reading license: {str(e)}"
