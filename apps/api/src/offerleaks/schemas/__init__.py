"""Pydantic request/response schemas (the HTTP-facing shapes).

Kept separate from `models/` (the ORM shapes) on purpose: an API response
shape and a database row shape drift apart the moment you add a computed
field or hide a column (e.g. `hashed_password` must never appear in a
response), so collapsing them into one class is a trap, not a
simplification.
"""
