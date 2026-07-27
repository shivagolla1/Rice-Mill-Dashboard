import base64
import hashlib
from cryptography.fernet import Fernet

def get_fernet(secret_key_str: str) -> Fernet:
    """Derive a 32-byte url-safe base64 key from secret string for Fernet AES encryption."""
    if not secret_key_str:
        secret_key_str = "RiceMillDashboardDefaultEncryptionKey2026!"
    key_bytes = hashlib.sha256(secret_key_str.encode('utf-8')).digest()
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)

def encrypt_data(raw_data: bytes, secret_key_str: str) -> bytes:
    """Encrypt raw bytes using AES Fernet encryption."""
    f = get_fernet(secret_key_str)
    return f.encrypt(raw_data)

def decrypt_data(encrypted_data: bytes, secret_key_str: str) -> bytes:
    """Decrypt AES Fernet encrypted bytes."""
    f = get_fernet(secret_key_str)
    return f.decrypt(encrypted_data)
