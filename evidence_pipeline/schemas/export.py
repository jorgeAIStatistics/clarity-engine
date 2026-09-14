"""Generate reviewable JSON Schema without invoking an LLM or remote service."""

import json
from pathlib import Path
from .pico import PICOExtraction

if __name__ == "__main__":
    destination = Path(__file__).with_name("pico.schema.json")
    destination.write_text(
        json.dumps(PICOExtraction.model_json_schema(), indent=2) + "\n"
    )
    print(destination)
