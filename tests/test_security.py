"""Unit tests for password hashing and JWT issuance."""

from __future__ import annotations

import time

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("S3cret!pass")
    assert h != "S3cret!pass"
    assert verify_password("S3cret!pass", h)
    assert not verify_password("wrong", h)


def test_verify_password_handles_garbage():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_jwt_roundtrip_contains_claims():
    token = create_access_token("user-123", extra_claims={"role": "admin"})
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_jwt_expired_rejected():
    token = create_access_token("u1", expires_minutes=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_jwt_tampered_rejected():
    token = create_access_token("u1")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "tamper")
    # touch time import to avoid lint flagging unused in some configs
    assert time.time() > 0
