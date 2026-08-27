"""Tests for JWT issuance and verification."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from offerleaks.auth.tokens import TokenError, TokenType, create_access_token, decode_token
from offerleaks.core.config import get_settings
from offerleaks.models.user import Role


def test_access_token_round_trips():
    user_id = uuid.uuid4()
    issued = create_access_token(user_id, Role.USER)

    payload = decode_token(issued.token, expected_type=TokenType.ACCESS)

    assert payload.user_id == user_id
    assert payload.role == Role.USER
    assert payload.token_type == TokenType.ACCESS
    assert payload.jti == issued.jti


def test_refresh_token_rejected_as_access_token():
    from offerleaks.auth.tokens import create_refresh_token

    issued = create_refresh_token(uuid.uuid4(), Role.USER)

    with pytest.raises(TokenError):
        decode_token(issued.token, expected_type=TokenType.ACCESS)


def test_expired_token_is_rejected():
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": Role.USER.value,
        "type": TokenType.ACCESS.value,
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=1),
        "iss": settings.jwt_issuer,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_wrong_signature_is_rejected():
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": Role.USER.value,
        "type": TokenType.ACCESS.value,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": settings.jwt_issuer,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        payload,
        "some-other-secret-entirely-unrelated-to-the-real-one",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_wrong_issuer_is_rejected():
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": Role.USER.value,
        "type": TokenType.ACCESS.value,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": "someone-elses-service",
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)
