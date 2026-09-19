import os
import time
import hmac
import hashlib
import struct
import base64
import secrets
from services.storage_service import get_system_setting, set_system_setting

B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

def generate_totp_secret(length: int = 16) -> str:
    """Generate a cryptographically secure Base32 secret for Google Authenticator."""
    return ''.join(secrets.choice(B32_ALPHABET) for _ in range(length))

def format_secret_readable(secret: str) -> str:
    """Format secret into spaced 4-character chunks for easy manual entry (e.g. ABCD EFGH JKLM NPQR)."""
    clean = (secret or '').replace(' ', '').upper()
    return ' '.join(clean[i:i+4] for i in range(0, len(clean), 4))

def get_totp_uri(secret: str, account: str = "Admin", issuer: str = "VideoLens") -> str:
    """Generate an otpauth:// URI recognized by Google Authenticator."""
    import urllib.parse
    clean_secret = (secret or '').replace(' ', '').upper()
    label = f"{issuer}:{account}"
    params = urllib.parse.urlencode({
        "secret": clean_secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": 6,
        "period": 30
    })
    return f"otpauth://totp/{urllib.parse.quote(label, safe=':')}?{params}"

def generate_totp_code(secret_b32: str, timestamp: int = None) -> str:
    """Generate the current 6-digit TOTP code according to RFC 6238."""
    if timestamp is None:
        timestamp = int(time.time())
    
    clean = (secret_b32 or '').replace(' ', '').upper()
    missing_padding = len(clean) % 8
    if missing_padding:
        clean += '=' * (8 - missing_padding)
        
    try:
        key = base64.b32decode(clean, casefold=True)
    except Exception:
        return "000000"
        
    step = timestamp // 30
    msg = struct.pack('>Q', step)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0f
    code = struct.unpack('>I', h[offset:offset+4])[0] & 0x7fffffff
    return str(code % 1000000).zfill(6)

def verify_totp_code(secret_b32: str, user_code: str, window: int = 2) -> bool:
    """
    Verify a 6-digit Google Authenticator code against a Base32 secret.
    Allows clock skew tolerance of +/- window steps (default: +/- 60s).
    """
    if not secret_b32 or not user_code:
        return False
        
    clean_code = str(user_code).strip().replace(' ', '')
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False
        
    now = int(time.time())
    for offset in range(-window, window + 1):
        target_timestamp = now + offset * 30
        expected = generate_totp_code(secret_b32, target_timestamp)
        if hmac.compare_digest(expected, clean_code):
            return True
            
    return False

def get_admin_totp_secret() -> str:
    """Get active admin TOTP secret from .env or database setting."""
    env_secret = os.getenv('ADMIN_TOTP_SECRET')
    if env_secret and env_secret.strip():
        return env_secret.strip().replace(' ', '').upper()
        
    db_secret = get_system_setting('admin_totp_secret')
    if db_secret and db_secret.strip():
        return db_secret.strip().replace(' ', '').upper()
        
    return None

def is_admin_2fa_enabled() -> bool:
    """Check if Google Authenticator 2FA is enabled for admin portal."""
    if os.getenv('ADMIN_TOTP_SECRET'):
        return True
    return get_system_setting('admin_2fa_enabled') == 'true'

def setup_admin_totp(secret: str, enable: bool = True):
    """Save admin TOTP secret and activation state in SQLite."""
    clean = (secret or '').replace(' ', '').upper()
    set_system_setting('admin_totp_secret', clean)
    set_system_setting('admin_2fa_enabled', 'true' if enable else 'false')

def disable_admin_totp():
    """Disable admin 2FA in SQLite."""
    set_system_setting('admin_2fa_enabled', 'false')
