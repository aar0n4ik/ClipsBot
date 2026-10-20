"""AES-256-GCM с ключом из пароля (PBKDF2-SHA256).

Формат совместим с WebCrypto в браузере (дашборд расшифровывает тем же паролем):
{"v":1,"iter":N,"salt":b64,"iv":b64,"ct":b64}  — ct уже содержит GCM-тег в конце.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 250_000


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_json(obj, password: str) -> bytes:
    salt, iv = os.urandom(16), os.urandom(12)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(_key(password, salt, ITERATIONS)).encrypt(iv, data, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return json.dumps({"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}).encode()


def decrypt_json(blob: bytes, password: str):
    env = json.loads(blob)
    d = lambda k: base64.b64decode(env[k])
    pt = AESGCM(_key(password, d("salt"), int(env["iter"]))).decrypt(d("iv"), d("ct"), None)
    return json.loads(pt)
