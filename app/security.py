import hashlib
import hmac
import os
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet

passwords = PasswordHasher()


def verify(stored, password):
    try:
        return passwords.verify(stored, password)
    except VerificationError:
        return False


def cipher():
    return Fernet(os.environ["TOKEN_KEY"].encode())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def random_token():
    return secrets.token_urlsafe(32)


def signature(filename, until):
    return hmac.new(os.environ["MEDIA_SECRET"].encode(),
                    f"{filename}:{until}".encode(), hashlib.sha256).hexdigest()


def media_url(filename):
    until = int(time.time()) + 3600
    return f'{os.environ["PUBLIC_URL"].rstrip("/")}/media/{filename}?until={until}&sig={signature(filename, until)}'
