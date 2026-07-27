#!/usr/bin/env python
"""
License Generator for Rice Mill Dashboard
Usage:
  python generate_license.py --name "Sapthagiri Rice Industries" --expiry "2027-07-06"
"""
import argparse
import json
import hmac
import hashlib
from datetime import datetime, timedelta

LICENSE_SECRET = b"SapthagiriRiceMillSecretSaltValue2026!"

def generate_key(name, expiry):
    # Verify date format
    try:
        datetime.strptime(expiry, "%Y-%m-%d")
    except ValueError:
        print(f"Error: Expiry date '{expiry}' is not in YYYY-MM-DD format.")
        return None

    name = name.strip()
    msg = f"{name}|{expiry}".encode("utf-8")
    sig = hmac.new(LICENSE_SECRET, msg, hashlib.sha256).hexdigest()

    license_data = {
        "industry_name": name,
        "expiry_date": expiry,
        "signature": sig
    }
    return license_data

def main():
    parser = argparse.ArgumentParser(description="Generate signed license files for Rice Mill Dashboard.")
    parser.add_argument("-n", "--name", help="Industry name")
    parser.add_argument("-e", "--expiry", help="Expiry date in YYYY-MM-DD format (default: 1 year from today)")
    parser.add_argument("-o", "--output", default="license.key", help="Output filepath (default: license.key)")
    
    args = parser.parse_args()
    
    name = args.name
    if not name:
        name = input("Enter Company Name: ").strip()
        while not name:
            name = input("Company Name cannot be empty. Please enter Company Name: ").strip()
            
    expiry = args.expiry
    if not expiry:
        default_expiry = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        expiry_input = input(f"Enter Expiry Date (YYYY-MM-DD) [Default: {default_expiry}]: ").strip()
        expiry = expiry_input if expiry_input else default_expiry
        
    lic = generate_key(name, expiry)
    if lic:
        out_path = args.output
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(lic, f, indent=2)
            
        print("\n=== LICENSE GENERATED SUCCESSFULLY ===")
        print(f"Industry Name : {lic['industry_name']}")
        print(f"Expiry Date   : {lic['expiry_date']}")
        print(f"Signature     : {lic['signature']}")
        print(f"Saved To      : {out_path}")
        print("======================================\n")
        print("Send the generated file to your client or copy-paste this raw text to activate:")
        print(json.dumps(lic))
        print("\n")

if __name__ == "__main__":
    main()
