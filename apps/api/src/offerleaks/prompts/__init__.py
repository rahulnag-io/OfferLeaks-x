"""Versioned prompt templates (architecture.md §0.6).

Stored as files, not inline strings, so a prompt version is a durable,
diffable artifact -- `ai_prompt_version` in config names which file here
is currently in use, and that version string is persisted alongside every
stored `Verdict` so a historical verdict's exact prompt is always known.
"""
