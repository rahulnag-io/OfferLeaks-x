"""Business logic layer.

Services orchestrate repositories and providers. They know nothing about
HTTP (no Request/Response objects) and nothing about SQL -- that keeps
business rules testable without spinning up FastAPI or a database.

Empty in Version 1: populated starting Version 2 (auth) and Version 3
(the upload -> OCR -> AI verdict vertical slice).
"""
