"""AI analysis behind an `AIProvider` interface (architecture.md §0.6).

Claude is the locked-in Version 3 model choice ("offer-letter fraud
detection is a reasoning-and-nuance task"). Every call goes through
`VerdictSchema` via the vendor's native tool-calling mode -- never
regex-parsed free text -- so a malformed response is a typed
`AIPermanentError`, not a silently-accepted bad verdict.
"""

import importlib.resources
from functools import lru_cache
from typing import Any, Protocol, cast

import anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from offerleaks.core.config import Settings
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError
from offerleaks.schemas.ai import VerdictSchema

_SUBMIT_VERDICT_TOOL_NAME = "submit_verdict"


class AIPermanentError(PermanentProviderError):
    pass


class AITransientError(TransientProviderError):
    pass


class AIProvider(Protocol):
    async def analyze_offer_letter(
        self, *, text: str, prompt_version: str
    ) -> VerdictSchema: ...


@lru_cache
def _load_prompt_template(prompt_version: str) -> str:
    try:
        return (
            importlib.resources.files("offerleaks.prompts")
            .joinpath(f"{prompt_version}.md")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise AIPermanentError(f"unknown prompt version {prompt_version!r}") from exc


def _verdict_tool_schema() -> dict[str, object]:
    # Derived from VerdictSchema itself so the tool's input schema and the
    # Pydantic model we validate the result against can never drift apart.
    schema = VerdictSchema.model_json_schema()
    return {
        "name": _SUBMIT_VERDICT_TOOL_NAME,
        "description": "Submit the structured fraud-risk verdict for the analyzed document.",
        "input_schema": schema,
    }


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise AIPermanentError("ANTHROPIC_API_KEY is not configured")

        self._model = settings.ai_model
        self._timeout = settings.ai_request_timeout_seconds
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze_offer_letter(self, *, text: str, prompt_version: str) -> VerdictSchema:
        template = _load_prompt_template(prompt_version)
        prompt = template.format(document_text=text)

        try:
            # The tool schema is derived dynamically from VerdictSchema
            # (see `_verdict_tool_schema`), so it's a plain dict rather
            # than the SDK's precise `ToolParam` TypedDict literal -- cast
            # at this one boundary rather than hand-duplicating the
            # schema in a form mypy can statically match, which would
            # reintroduce exactly the drift this approach avoids.
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                timeout=self._timeout,
                tools=cast(Any, [_verdict_tool_schema()]),
                tool_choice=cast(Any, {"type": "tool", "name": _SUBMIT_VERDICT_TOOL_NAME}),
                messages=[{"role": "user", "content": prompt}],
            )
        except (APITimeoutError, APIConnectionError) as exc:
            raise AITransientError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code == 429 or exc.status_code >= 500:
                raise AITransientError(str(exc)) from exc
            raise AIPermanentError(str(exc)) from exc

        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            raise AIPermanentError("model did not call the submit_verdict tool")

        try:
            return VerdictSchema.model_validate(tool_use_block.input)
        except ValidationError as exc:
            raise AIPermanentError(f"model output failed schema validation: {exc}") from exc
