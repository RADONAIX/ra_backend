"""Unit tests for password hashing and JWT issuance."""

from __future__ import annotations

import time

import bcrypt
import jwt
import pytest
from argon2 import PasswordHasher

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("S3cret!pass")
    assert h != "S3cret!pass"
    assert verify_password("S3cret!pass", h)
    assert not verify_password("wrong", h)


def test_hash_password_is_argon2id():
    assert hash_password("Test1234!").startswith("$argon2id$")


def test_verify_argon2_hash():
    h = hash_password("Test1234!")
    assert verify_password("Test1234!", h) is True
    assert verify_password("WrongPassword", h) is False


def test_verify_legacy_bcrypt_hash():
    # A pre-migration bcrypt hash must still verify (transition path).
    bcrypt_hash = bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode()
    assert bcrypt_hash.startswith("$2")
    assert verify_password("Test1234!", bcrypt_hash) is True
    assert verify_password("WrongPassword", bcrypt_hash) is False


def test_verify_password_never_raises_on_bad_input():
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "") is False
    assert verify_password("anything", "$argon2id$garbage") is False


def test_needs_rehash_bcrypt_true_argon2_false():
    bcrypt_hash = bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode()
    assert needs_rehash(bcrypt_hash) is True
    assert needs_rehash(hash_password("Test1234!")) is False


def test_needs_rehash_when_argon2_params_change():
    # A hash made with weaker params should be flagged for rehash.
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    weak_hash = weak.hash("Test1234!")
    assert needs_rehash(weak_hash) is True


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


def test_refresh_token_carries_session_claims():
    token = create_refresh_token("user-9", session_id="sess-1", jti="jti-abc")
    payload = decode_token(token)
    assert payload["type"] == "refresh"
    assert payload["sub"] == "user-9"
    assert payload["sid"] == "sess-1"
    assert payload["jti"] == "jti-abc"


def test_access_and_refresh_token_types_differ():
    access = decode_token(create_access_token("u1"))
    refresh = decode_token(create_refresh_token("u1", session_id="s", jti="j"))
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"
