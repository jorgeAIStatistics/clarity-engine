"""Daily service entry point; delegates bounded runs to the same tested CLI."""

import os
import signal
import threading
from .cli import main


def run():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    interval = int(os.getenv("PIPELINE_INTERVAL_SECONDS", "86400"))
    if interval < 60:
        raise ValueError("Pipeline interval must be at least 60 seconds")
    argv = [
        "run",
        "--targets",
        os.getenv("PIPELINE_TARGETS", "evidence_pipeline/targets.example.json"),
    ]
    if os.getenv("PIPELINE_WITH_GRAPH", "false").lower() == "true":
        argv.append("--with-graph")
    while not stop.is_set():
        try:
            main(argv)
        except SystemExit:
            pass  # Failed runs are already recorded; retain source checkpoints.
        stop.wait(interval)


if __name__ == "__main__":
    run()
