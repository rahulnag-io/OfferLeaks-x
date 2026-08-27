"""Tests for password hashing."""

from offerleaks.auth.security import hash_password, verify_password


def test_hash_is_not_the_plaintext():
    hashed = hash_password("correcthorsebattery")
    assert hashed != "correcthorsebattery"


def test_verify_accepts_correct_password():
    hashed = hash_password("correcthorsebattery")
    assert verify_password("correcthorsebattery", hashed) is True


def test_verify_rejects_incorrect_password():
    hashed = hash_password("correcthorsebattery")
    assert verify_password("wrong-password", hashed) is False


def test_same_password_hashes_differently_each_time():
    # Argon2 salts each hash, so two hashes of the same password should
    # never be equal -- a static hash would mean no salt, a real weakness.
    assert hash_password("correcthorsebattery") != hash_password("correcthorsebattery")
