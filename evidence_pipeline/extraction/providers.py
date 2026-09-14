"""Bounded provider adapters: JSON only, no prose fallback or hidden retries."""

from dataclasses import dataclass
import copy
import json
import httpx
from ..common import PipelineError


@dataclass(frozen=True)
class ProviderOutput:
    payload: dict
    request_id: str | None
    input_tokens: int
    output_tokens: int


def wire_schema(schema):
    """Common provider subset; complete constraints still enforced by Pydantic."""
    result = copy.deepcopy(schema)
    unsupported = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "multipleOf",
    }

    def walk(node):
        if isinstance(node, dict):
            constraints = {k: node.pop(k) for k in list(node) if k in unsupported}
            if constraints:
                node["description"] = (
                    node.get("description", "")
                    + " Runtime constraints: "
                    + json.dumps(constraints)
                ).strip()
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(result)
    return result


class StructuredProvider:
    def __init__(self, provider, model, api_key, client=None, max_output_tokens=16000):
        if provider not in ("openai", "anthropic") or not model or not api_key:
            raise PipelineError("extraction_provider_configuration_missing")
        if not 1024 <= max_output_tokens <= 32000:
            raise ValueError("Invalid output token cap")
        self.name = provider
        self.model = model
        self.api_key = api_key
        self.maximum = max_output_tokens
        self.client = client or httpx.Client(timeout=120, follow_redirects=False)
        self.owned = client is None

    def close(self):
        if self.owned:
            self.client.close()

    def extract(self, instructions, sources, schema):
        content = json.dumps(
            {"documents": [{"source_id": s.id, "text": s.text} for s in sources]},
            ensure_ascii=False,
        )
        if self.name == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": "Bearer " + self.api_key}
            body = {
                "model": self.model,
                "store": False,
                "max_completion_tokens": self.maximum,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "pico_extraction",
                        "strict": True,
                        "schema": wire_schema(schema),
                    },
                },
            }
        else:
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
            body = {
                "model": self.model,
                "max_tokens": self.maximum,
                "system": instructions,
                "messages": [{"role": "user", "content": content}],
                "tools": [
                    {
                        "name": "record_pico",
                        "description": "Record only the reported PICO facts in supplied source documents.",
                        "strict": True,
                        "input_schema": wire_schema(schema),
                    }
                ],
                "tool_choice": {
                    "type": "tool",
                    "name": "record_pico",
                    "disable_parallel_tool_use": True,
                },
            }
        try:
            response = self.client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as error:
            raise PipelineError(
                "extraction_provider_http_" + str(error.response.status_code)
            ) from None
        except (httpx.HTTPError, ValueError):
            raise PipelineError("extraction_provider_request_failed") from None
        try:
            if self.name == "openai":
                choices = data["choices"]
                if (
                    len(choices) != 1
                    or choices[0]["finish_reason"] != "stop"
                    or choices[0]["message"].get("refusal")
                ):
                    raise PipelineError("extraction_refused_or_incomplete")
                payload = json.loads(choices[0]["message"]["content"])
                usage = data.get("usage", {})
                inp = usage.get("prompt_tokens", 0)
                out = usage.get("completion_tokens", 0)
            else:
                blocks = data["content"]
                tools = [
                    b
                    for b in blocks
                    if b.get("type") == "tool_use" and b.get("name") == "record_pico"
                ]
                if (
                    data["stop_reason"] != "tool_use"
                    or len(tools) != 1
                    or any(b.get("type") != "tool_use" for b in blocks)
                ):
                    raise PipelineError("extraction_refused_or_incomplete")
                payload = tools[0]["input"]
                usage = data.get("usage", {})
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
            if not isinstance(payload, dict):
                raise PipelineError("extraction_not_json_object")
            return ProviderOutput(
                payload,
                response.headers.get("request-id")
                or response.headers.get("x-request-id")
                or data.get("id"),
                inp,
                out,
            )
        except (KeyError, TypeError, ValueError, IndexError):
            raise PipelineError("extraction_response_malformed") from None
