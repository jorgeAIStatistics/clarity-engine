"""Idempotently import the verified deployment seed into namespaced durable state."""

import gzip
import json
from pathlib import Path
from .state import State
from .schemas.pico import ExtractionEnvelope

SEED = Path(__file__).with_name("deployment-seed.json.gz")
ALLOWED = {
    "candidate",
    "extraction",
    "graph_receipt",
    "ingestion",
    "checkpoint",
    "window",
    "activation",
    "job",
}


def bootstrap(location, seed_path=SEED):
    if not seed_path.exists():
        return 0
    data = json.loads(gzip.decompress(seed_path.read_bytes()))
    if data.get("version") != 1:
        raise ValueError("Unsupported seed version")
    for row in data["records"]:
        if row["kind"] not in ALLOWED:
            raise ValueError("Invalid seed record type")
        if row["kind"] == "extraction":
            env = ExtractionEnvelope.model_validate_json(
                json.dumps(row["value"]["envelope"])
            )
            if env.provider == "fixture":
                raise ValueError("Synthetic seed prohibited")
    state = State(location)
    inserted = 0
    try:
        with state.transaction():
            for row in data["records"]:
                if state.get(row["kind"], row["id"]) is None:
                    state.put(row["kind"], row["id"], row["value"])
                    inserted += 1
    finally:
        state.close()
    return inserted
