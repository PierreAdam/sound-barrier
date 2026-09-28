import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet


def generate_secret_key() -> str:
    return Fernet.generate_key().decode()


class PasswordCipher:
    """Reversible password encryption.

    Subsonic token auth sends md5(password + salt), so the server must be able to
    recover the plaintext password. Passwords are therefore encrypted, not hashed.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, password: str) -> bytes:
        return self._fernet.encrypt(password.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()


def subsonic_token(password: str, salt: str) -> str:
    return hashlib.md5((password + salt).encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
