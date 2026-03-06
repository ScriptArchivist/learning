import base64
import hashlib
import hmac
import json
import time
import uuid

from src.config import settings


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign(data: bytes) -> str:
    sig = hmac.new(
        settings.secret_key.encode(),
        data,
        hashlib.sha256,
    ).digest()

    return b64url_encode(sig)


def create_access_token(user_id: int, role: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    now = int(time.time())

    payload = {
        "sub": str(user_id),
        "role": role,
        "iss": "identity-service",
        "aud": "video-platform",
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
    }

    header_b64 = b64url_encode(json.dumps(header).encode())
    payload_b64 = b64url_encode(json.dumps(payload).encode())

    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = sign(signing_input)

    return f"{header_b64}.{payload_b64}.{signature}"


def create_refresh_token() -> str:
    return str(uuid.uuid4())