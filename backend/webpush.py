"""Web Push (RFC 8030/8291/8292) ohne Zusatzpaket: Nachricht verschlüsseln (aes128gcm) und mit VAPID signieren.

Funktioniert mit Apple (web.push.apple.com, iOS/iPadOS ab 16.4 für Home-Bildschirm-Apps), Chrome und Firefox.
Schlüssel: VAPID_PRIVATE_KEY (Base64url, 32 Byte) als GitHub-Secret; der öffentliche Schlüssel steht in der App.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC

SUB = "mailto:kairo-push@users.noreply.github.com"


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    h = HMAC(salt, hashes.SHA256())
    h.update(ikm)
    return h.finalize()


def _hkdf_expand(prk: bytes, info: bytes, n: int) -> bytes:
    h = HMAC(prk, hashes.SHA256())
    h.update(info + b"\x01")
    return h.finalize()[:n]


def _pub_bytes(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_key(raw_b64: str):
    return ec.derive_private_key(int.from_bytes(b64d(raw_b64), "big"), ec.SECP256R1())


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None, eph=None) -> bytes:
    """aes128gcm-Inhaltskodierung (RFC 8291): Kopf (Salt, Satzgröße, Absender-Schlüssel) + verschlüsselter Datensatz."""
    ua_pub = b64d(p256dh)
    auth_secret = b64d(auth)
    eph = eph or ec.generate_private_key(ec.SECP256R1())
    as_pub = _pub_bytes(eph)
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf_expand(_hkdf_extract(auth_secret, shared), b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    prk = _hkdf_extract(salt, ikm)
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">I", 4096) + bytes([len(as_pub)]) + as_pub + ct


def vapid_header(endpoint: str, key) -> str:
    u = urlparse(endpoint)
    head = b64e(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64e(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUB},
                             separators=(",", ":")).encode())
    der = key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    jwt = f"{head}.{claims}.{b64e(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={b64e(_pub_bytes(key))}"


def send(sub: dict, data: dict, key, ttl: int = 36 * 3600) -> int:
    """Eine Nachricht an ein Abo senden. Rückgabe: HTTP-Status (201 = angenommen, 404/410 = Abo ungültig)."""
    import requests

    body = encrypt(json.dumps(data, ensure_ascii=False).encode(), sub["keys"]["p256dh"], sub["keys"]["auth"])
    r = requests.post(sub["endpoint"], data=body, timeout=20, headers={
        "Authorization": vapid_header(sub["endpoint"], key), "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream", "TTL": str(ttl), "Urgency": "normal"})
    return r.status_code
