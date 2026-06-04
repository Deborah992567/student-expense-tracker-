import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, email: str, issuer: str = "StudentSpend") -> str:
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not secret or not code.isdigit():
        return False

    current_counter = int(time.time() // 30)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_totp(secret, current_counter + offset), code):
            return True
    return False


def _totp(secret: str, counter: int) -> str:
    key = _decode_base32(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _decode_base32(secret: str) -> bytes:
    padding = "=" * (-len(secret) % 8)
    return base64.b32decode(secret + padding, casefold=True)
