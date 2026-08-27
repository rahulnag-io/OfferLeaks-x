"""Password hashing.

Argon2id (via argon2-cffi) rather than bcrypt: it's the current OWASP
recommendation, it's memory-hard (more resistant to GPU cracking), and it
has no 72-byte input truncation footgun to worry about.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True if the stored hash was made with outdated Argon2 parameters.

    Callers can use this on successful login to transparently upgrade a
    user's stored hash without forcing a password reset.
    """
    return _hasher.check_needs_rehash(hashed_password)
