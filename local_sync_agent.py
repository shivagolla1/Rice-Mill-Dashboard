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

def sync_now(cfg=None):
    if cfg is None:
        cfg = load_config()
        
    cloud_url = cfg.get("CLOUD_URL", "").rstrip('/')
    sync_token = cfg.get("SYNC_SECRET_TOKEN", "")
    enc_key = cfg.get("ENCRYPTION_KEY", "")
    mdb_path = find_local_mdb(cfg.get("MDB_PATH", ""))

    if not mdb_path or not os.path.exists(mdb_path):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Database file not found: {cfg.get('MDB_PATH')}")
        return False

    if not cloud_url or "your-app" in cloud_url:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Please set your valid Railway CLOUD_URL in sync_config.txt")
        return False

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Syncing: {os.path.basename(mdb_path)} -> {cloud_url} ...")

    try:
        with open(mdb_path, 'rb') as f:
            raw_bytes = f.read()

        raw_size_mb = len(raw_bytes) / (1024 * 1024)
        print(f"  * Reading file ({raw_size_mb:.2f} MB)")

        compressed_bytes = gzip.compress(raw_bytes)
        comp_size_mb = len(compressed_bytes) / (1024 * 1024)
        print(f"  * Compressed size: {comp_size_mb:.2f} MB (saved {((1 - comp_size_mb/raw_size_mb)*100):.1f}%)")

        encrypted_payload = crypto_utils.encrypt_data(compressed_bytes, enc_key)
        print(f"  * AES-256 encrypted payload ready")

        # Send in 256 KB chunks to bypass Windows 10053 socket aborts and HTTP proxy limits
        CHUNK_SIZE = 256 * 1024
        total_chunks = (len(encrypted_payload) + CHUNK_SIZE - 1) // CHUNK_SIZE
        upload_id = hashlib.md5(f"{time.time()}".encode()).hexdigest()[:10]

        import base64, requests
        session = requests.Session()
        endpoint = f"{cloud_url}/api/sync-database"

        print(f"  * Uploading payload in {total_chunks} chunks (256 KB each)...")
        resp = None

        for i in range(total_chunks):
            chunk = encrypted_payload[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            b64_chunk = base64.b64encode(chunk).decode('utf-8')
            json_body = {
                'token': sync_token,
                'data': b64_chunk,
                'chunk_idx': i,
                'total_chunks': total_chunks,
                'upload_id': upload_id
            }
            headers = {
                'Content-Type': 'application/json',
                'X-Sync-Token': sync_token,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) RiceMillSyncAgent/1.0'
            }
            resp = session.post(endpoint, json=json_body, headers=headers, timeout=120)

            if resp.status_code != 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [FAILED] Chunk {i+1}/{total_chunks} failed: {resp.text}")
                return False

        if resp and resp.status_code == 200:
            res = resp.json()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [SUCCESS] Database synced to cloud! ({res.get('size_bytes', 0)} bytes)")
            return True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [FAILED] Upload failed on final chunk")
            return False




    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Sync failed: {e}")
        return False


def watch_loop():
    cfg = load_config()
    mode = cfg.get("SYNC_MODE", "AUTO").upper()
    interval = int(cfg.get("CHECK_INTERVAL_SEC", "30"))

    print("==========================================================")
    print("  SGRI Rice Mill Dashboard — Local Cloud Sync Agent")
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
                        if sync_now(cfg):
                            last_hash = current_hash
                            last_mtime = current_mtime
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for database file or USB drive...")

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Watcher exception: {e}")

        time.sleep(interval)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        sync_now()
    else:
        watch_loop()
