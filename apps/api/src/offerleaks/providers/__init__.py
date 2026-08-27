"""External services behind interfaces (AI, OCR, reputation sources).

Per architecture.md §0.6/§0.13: nothing outside this package ever imports
a vendor SDK directly. Business logic depends on abstract provider
interfaces (e.g. AIProvider, OCRProvider); concrete implementations
(AnthropicProvider, DocumentAIProvider, ...) live here and are swapped
via configuration, not code changes.
"""
