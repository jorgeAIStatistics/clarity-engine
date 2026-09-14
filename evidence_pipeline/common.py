import hashlib
import json
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc)


class PipelineError(RuntimeError):
    """Safe operator-facing error code. Never include credentials or source text."""
