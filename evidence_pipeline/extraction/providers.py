"""Bounded provider adapters: JSON only, no prose fallback or hidden retries."""

from dataclasses import dataclass
import copy
import json
import httpx
from ..common import PipelineError
from .transport import compact_schema, TRANSPORT_INSTRUCTIONS, VERSION, reference_schema


@dataclass(frozen=True)
class ProviderOutput:
    payload: dict
    request_id: str | None
    input_tokens: int
    output_tokens: int
    transport: dict | None = None
    raw_payload: dict | None = None


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
        "maxItems",
        "minItems",
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
    supports_repairs = True

    def __init__(self, provider, model, api_key, client=None, max_output_tokens=32000):
        if provider not in ("openai", "anthropic") or not model or not api_key:
            raise PipelineError("extraction_provider_configuration_missing")
        if not 1024 <= max_output_tokens <= 32000:
            raise ValueError("Invalid output token cap")
        self.name = provider
        self.model = model
        self.api_key = api_key
        self.maximum = max_output_tokens
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(300, connect=20), follow_redirects=False
        )
        self.owned = client is None

    def close(self):
        if self.owned:
            self.client.close()

    def repair(self, instructions, sources, schema, previous, issues):
        from .repair import (
            INSTRUCTIONS as REPAIR_INSTRUCTIONS,
            REPAIR_VERSION,
            repair_schema,
        )

        if self.name != "anthropic":
            raise PipelineError("repair_provider_unsupported")
        content = json.dumps(
            {
                "documents": [{"source_id": s.id, "text": s.text} for s in sources],
                "rejected_transport": previous.payload,
                "validation_issues": issues,
                "approved_pico_schema": schema,
            },
            ensure_ascii=False,
        )
        try:
            response = self.client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": self.model,
                    "max_tokens": min(self.maximum, 16000),
                    "system": instructions
                    + "\n"
                    + TRANSPORT_INSTRUCTIONS
                    + "\n"
                    + REPAIR_INSTRUCTIONS,
                    "messages": [{"role": "user", "content": content}],
                    "tools": [
                        {
                            "name": "repair_pico",
                            "description": "Repair rejected structured fields only.",
                            "strict": True,
                            "input_schema": wire_schema(repair_schema(schema)),
                        }
                    ],
                    "tool_choice": {
                        "type": "tool",
                        "name": "repair_pico",
                        "disable_parallel_tool_use": True,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as error:
            raise PipelineError(
                "extraction_provider_http_" + str(error.response.status_code)
            ) from None
        except (httpx.HTTPError, ValueError):
            raise PipelineError("extraction_provider_request_failed") from None
        blocks = data.get("content", [])
        if (
            data.get("stop_reason") != "tool_use"
            or len(blocks) != 1
            or blocks[0].get("type") != "tool_use"
            or blocks[0].get("name") != "repair_pico"
        ):
            raise PipelineError("repair_refused_or_incomplete")
        patch = blocks[0].get("input")
        if not isinstance(patch, dict):
            raise PipelineError("repair_response_malformed")
        usage = data.get("usage", {})
        return ProviderOutput(
            previous.payload,
            response.headers.get("request-id") or data.get("id"),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            {
                "version": VERSION,
                "repair_version": REPAIR_VERSION,
                "previous_request_id": previous.request_id,
                "patch": patch,
                "validation_issues": issues,
            },
        )

    def extract(self, instructions, sources, schema):
        original_schema = schema
        if self.name == "anthropic":
            schema = compact_schema(schema)
            instructions += (
                "\n"
                + TRANSPORT_INSTRUCTIONS
                + "\nExpanded reference schema:\n"
                + json.dumps(wire_schema(reference_schema(original_schema)))
            )
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
                if data["stop_reason"] == "max_tokens":
                    raise PipelineError("extraction_output_token_limit")
                tools = [
                    b
                    for b in blocks
                    if b.get("type") == "tool_use" and b.get("name") == "record_pico"
                ]
                if (
                    data["stop_reason"] != "tool_use"
                    or len(tools) != 1
                    or len(blocks) != 1
                    or any(b.get("type") != "tool_use" for b in blocks)
                ):
                    raise PipelineError("extraction_refused_or_incomplete")
                payload = tools[0]["input"]
                usage = data.get("usage", {})
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
            if not isinstance(payload, dict):
                raise PipelineError("extraction_not_json_object")
            transport = None
            if self.name == "anthropic":
                transport = {"version": VERSION, "payload": payload}
            return ProviderOutput(
                payload,
                response.headers.get("request-id")
                or response.headers.get("x-request-id")
                or data.get("id"),
                inp,
                out,
                transport,
            )
        except (KeyError, TypeError, ValueError, IndexError):
            raise PipelineError("extraction_response_malformed") from None
