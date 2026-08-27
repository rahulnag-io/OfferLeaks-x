"""Authentication & authorization.

This package is deliberately isolated from `services/` (architecture.md
§0.13): token issuance, verification, refresh, password hashing, and
role-checking live here and nowhere else. `services/auth_service.py`
depends on this package for the token/hashing primitives, the same way it
would depend on any other `AuthProvider`-style boundary -- callers never
touch PyJWT, argon2, or Redis session keys directly.
"""
