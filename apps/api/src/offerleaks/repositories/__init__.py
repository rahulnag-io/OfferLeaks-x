"""Data access layer (SQLAlchemy).

Repositories are the only layer allowed to import SQLAlchemy models and
issue queries. Services depend on repository interfaces, not on the ORM
directly, so persistence can be swapped or mocked in tests.
"""
