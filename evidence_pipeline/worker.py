"""Daily service entry point; delegates bounded runs to the same tested CLI."""

import os
import signal
import threading
from .cli import main
from .config import Settings
from .state import State
from .common import PipelineError, now
from datetime import datetime, timedelta


def check_activation(settings):
    state = State(settings.state_path)
    try:
        activation = state.get("activation", "daily-worker")
        if activation and activation.get("enabled") is not True:
            raise PipelineError("daily_worker_activation_blocked")
    finally:
        state.close()


def run():
    env_file = os.getenv("PIPELINE_ENV_FILE")
    settings = Settings.from_env(env_file)
    check_activation(settings)
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
        state = State(settings.state_path)
        schedule = state.get("schedule", "daily") or {}
        due = (
            datetime.fromisoformat(schedule["next_run_at"])
            if schedule.get("next_run_at")
            else now()
        )
        state.close()
        if due > now():
            stop.wait(min(60, (due - now()).total_seconds()))
            continue
        try:
            main(argv)
        except SystemExit:
            pass  # Failed runs are already recorded; retain source checkpoints.
        state = State(settings.state_path)
        state.put(
            "schedule",
            "daily",
            {
                "last_finished_at": now().isoformat(),
                "next_run_at": (now() + timedelta(seconds=interval)).isoformat(),
            },
        )
        state.close()
        stop.wait(min(interval, 60))


if __name__ == "__main__":
    run()
