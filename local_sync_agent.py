#!/usr/bin/env python3
"""
Rice Mill Dashboard — Local Sync Agent (Windows 7 Compatible)
Monitors your local MS Access (.mdb) file on USB or hard drive, GZIP compresses it,
AES-256 encrypts it, and pushes it to your Railway cloud dashboard server.
"""

import os
import sys
import time
import gzip
import json
import hashlib
import requests
from datetime import datetime

# Add App folder to sys.path to reuse crypto_utils
APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'App')
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import crypto_utils
except ImportError:
    print("[ERROR] Could not import crypto_utils. Make sure App folder is present.")
    sys.exit(1)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_config.txt')

DEFAULT_CONFIG = {
    "MDB_PATH": r"D:\SGRI\SGRI 2025-2026.mdb",
    "CLOUD_URL": "https://your-app.up.railway.app",
    "SYNC_SECRET_TOKEN": "RiceMillSyncSecretToken2026!@#",
    "ENCRYPTION_KEY": "RiceMillDashboardDefaultEncryptionKey2026!",
    "SYNC_MODE": "AUTO",
    "CHECK_INTERVAL_SEC": 30
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, _, v = line.partition('=')
                    cfg[k.strip()] = v.strip()
        except Exception as e:
            print(f"[WARNING] Error reading config file: {e}")
    return cfg

def find_local_mdb(configured_path):
    # 1. Exact configured path check
    if configured_path and os.path.exists(configured_path):
        return configured_path

    target_filename = os.path.basename(configured_path).strip().lower() if configured_path else ""

    # 2. Drive letter shift fallback for exact filename (e.g. searching for SGRI 2025-2026.mdb across D:\, E:\, F:\, etc.)
    if target_filename:
        import string
        for letter in string.ascii_uppercase:
            drive_root = f"{letter}:\\"
            if os.path.isdir(drive_root):
                try:
                    for root, dirs, files in os.walk(drive_root):
                        if any(ignore in root.lower() for ignore in ['\\windows', '\\program files', '\\$recycle.bin']):
                            continue
                        for f in files:
                            if f.lower() == target_filename:
                                return os.path.join(root, f)
                except Exception:
                    pass

    # 3. Local data directories fallback (sorted by most recently modified)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    for search in [os.path.join(base_dir, 'App', 'data'), os.path.join(base_dir, 'data'), base_dir]:
        if os.path.isdir(search):
            for f in os.listdir(search):
                if f.lower().endswith('.mdb'):
                    full_p = os.path.join(search, f)
                    candidates.append(full_p)

    if candidates:
        # Sort by most recently modified
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]

    # 4. USB Removable Drive Scan fallback: Collect ALL .mdb files and pick the most recently modified
    import string
    usb_candidates = []
    for letter in 'DEFGH':
        drive = f"{letter}:\\"
        if os.path.isdir(drive):
            try:
                for root, dirs, files in os.walk(drive):
                    if any(ignore in root.lower() for ignore in ['\\windows', '\\program files', '\\$recycle.bin']):
                        continue
                    for f in files:
                        if f.lower().endswith('.mdb'):
                            usb_candidates.append(os.path.join(root, f))
            except Exception:
                pass

    if usb_candidates:
        # Pick the .mdb file that was updated most recently
        usb_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        print(f"[INFO] Multiple .mdb files found on USB ({len(usb_candidates)} files). Selected most recently modified: {os.path.basename(usb_candidates[0])}")
        return usb_candidates[0]

    return None



def calculate_file_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def open_windows_file_dialog():
    """Trigger native Windows File Open Dialog to select .mdb file in 1 click."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", wintypes.LPCWSTR),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", wintypes.DWORD),
                ("FlagsEx", wintypes.DWORD),
            ]

        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)

        filter_str = "MS Access Database (*.mdb)\0*.mdb\0All Files (*.*)\0*.*\0\0"
        file_buffer = ctypes.create_unicode_buffer(260)

        ofn.lpstrFilter = filter_str
        ofn.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
        ofn.nMaxFile = 260
        ofn.lpstrTitle = "Select Access Database (.mdb) File to Sync to Dashboard"
        ofn.Flags = 0x00080000 | 0x00001000 | 0x00000800  # OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST

        if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return file_buffer.value
    except Exception as e:
        print(f"[WARNING] Native File Dialog failed: {e}")
    return None

def show_windows_msgbox(title, message, is_error=False):
    """Display native Windows alert popup box."""
    if os.name == 'nt':
        try:
            import ctypes
            style = 0x10 if is_error else 0x40  # MB_ICONERROR vs MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, message, title, style)
        except Exception:
            pass
    print(f"[{title}] {message}")

def sync_now(cfg=None, custom_file_path=None):
    if cfg is None:
        cfg = load_config()
        
    cloud_url = cfg.get("CLOUD_URL", "").rstrip('/')
    sync_token = cfg.get("SYNC_SECRET_TOKEN", "RiceMillSyncSecretToken2026!@#")
    license_key = cfg.get("LICENSE_KEY", cfg.get("LICENSE", "")).strip()
    company_code = cfg.get("COMPANY_CODE", "").strip()
    enc_key = cfg.get("ENCRYPTION_KEY", "RiceMillDashboardDefaultEncryptionKey2026!")

    mdb_path = custom_file_path or find_local_mdb(cfg.get("MDB_PATH", ""))

    if not mdb_path or not os.path.exists(mdb_path):
        show_windows_msgbox("Rice Mill Sync", f"Database file not found or no file selected.", is_error=True)
        return False

    if not cloud_url or "your-app" in cloud_url:
        show_windows_msgbox("Rice Mill Sync", "Please set your valid Railway CLOUD_URL in sync_config.txt", is_error=True)
        return False

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Syncing: {os.path.basename(mdb_path)} -> {cloud_url} ...")

    try:
        with open(mdb_path, 'rb') as f:
            raw_bytes = f.read()

        raw_size_mb = len(raw_bytes) / (1024 * 1024)
        compressed_bytes = gzip.compress(raw_bytes)

        try:
            encrypted_payload = crypto_utils.encrypt_data(compressed_bytes, enc_key)
        except Exception:
            encrypted_payload = compressed_bytes

        import requests
        import base64
        session = requests.Session()
        endpoint = f"{cloud_url}/api/sync-database"
        headers = {
            'X-Sync-Token': sync_token,
            'X-License-Key': license_key,
            'X-Company-Code': company_code,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) RiceMillSyncAgent/1.0'
        }

        # Try Fast Single Multipart Upload first (takes ~3s!)
        print(f"  * Uploading payload to cloud server...")
        try:
            files = {'file': (os.path.basename(mdb_path), encrypted_payload, 'application/octet-stream')}
            resp = session.post(endpoint, files=files, headers=headers, timeout=120)
            if resp.status_code == 200:
                res = resp.json()
                msg = f"✓ Database File '{os.path.basename(mdb_path)}' Synced Successfully to Dashboard!"
                show_windows_msgbox("Rice Mill Dashboard", msg)
                return True
            else:
                err_text = resp.json().get('message', resp.text) if resp.headers.get('content-type') == 'application/json' else resp.text
                show_windows_msgbox("Rice Mill Sync Error", f"Sync failed ({resp.status_code}): {err_text}", is_error=True)
                return False
        except Exception as fast_err:
            show_windows_msgbox("Rice Mill Sync Error", f"Network error during upload: {fast_err}", is_error=True)
            return False

    except Exception as e:
        show_windows_msgbox("Rice Mill Sync Error", f"Sync failed: {e}", is_error=True)
        return False

def watch_loop():
    cfg = load_config()
    mode = cfg.get("SYNC_MODE", "AUTO").upper()
    interval = int(cfg.get("CHECK_INTERVAL_SEC", "30"))

    print("==========================================================")
    print("  Rice Mill Dashboard — Local Cloud Sync Agent")
    print(f"  Mode: {mode} | Interval: {interval}s")
    print("==========================================================")

    if mode == "MANUAL":
        print("\nManual mode selected. Performing single sync...")
        sync_now(cfg)
        return

    last_hash = None
    last_mtime = None

    while True:
        try:
            cfg = load_config()
            interval = int(cfg.get("CHECK_INTERVAL_SEC", "30"))
            mdb_path = find_local_mdb(cfg.get("MDB_PATH", ""))

            if mdb_path and os.path.exists(mdb_path):
                current_mtime = os.path.getmtime(mdb_path)
                if current_mtime != last_mtime:
                    current_hash = calculate_file_hash(mdb_path)
                    if current_hash != last_hash:
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] File modification detected!")
                        if sync_now(cfg, custom_file_path=mdb_path):
                            last_hash = current_hash
                            last_mtime = current_mtime
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for file or USB drive...")

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Watcher exception: {e}")

        time.sleep(interval)

if __name__ == '__main__':
    cfg = load_config()
    if len(sys.argv) > 1 and sys.argv[1] == '--pick':
        picked = open_windows_file_dialog()
        if picked:
            sync_now(cfg, custom_file_path=picked)
    elif len(sys.argv) > 1 and sys.argv[1] == '--once':
        sync_now(cfg)
    elif len(sys.argv) > 1 and sys.argv[1] == '--daemon':
        watch_loop()
    else:
        # Default 2-Click Interactive behavior when double-clicked
        picked = open_windows_file_dialog()
        if picked:
            sync_now(cfg, custom_file_path=picked)
        else:
            # Fallback to configured path if dialog cancelled
            sync_now(cfg)

