"""Supervise the API and bounded research scheduler on the existing Render service.

No threads inside Gunicorn, no in-memory checkpoints, and no extra paid service.
Render restarts this parent if either required child exits unexpectedly.
"""
import os
import signal
import subprocess
import sys
import time


def commands(env):
    result = [[sys.executable, '-m', 'gunicorn', 'app:app', '--bind', f"0.0.0.0:{env.get('PORT', '8000')}",
               '--timeout', '120', '--workers', '1', '--threads', '4']]
    database = env.get('CLARITY_RESEARCH_DATABASE_URL') or env.get('DATABASE_URL', '')
    if env.get('CLARITY_RESEARCH_ENABLED', '1') == '1' and database.startswith(('postgres://', 'postgresql://')):
        worker = [sys.executable, '-m', 'living_research', '--config', 'living_research/config.example.json', 'watch']
        if env.get('ANTHROPIC_API_KEY'): worker.append('--llm')
        result.append(worker)
    # Keeps the Neo4j connection and the catalog cache warm from inside the box. Off with
    # CLARITY_WARM_ENABLED=0; interval in seconds with CLARITY_WARM_INTERVAL.
    if env.get('CLARITY_WARM_ENABLED', '1') == '1':
        result.append([sys.executable, '-m', 'evidence.warm', f"http://127.0.0.1:{env.get('PORT', '8000')}"])
    if env.get('CLARITY_PICO_ENABLED') == '1':
        if not database.startswith(('postgres://', 'postgresql://')):
            raise RuntimeError('PICO worker requires persistent PostgreSQL')
        result.append([sys.executable, '-m', 'evidence_pipeline.worker'])
    return result


def main():
    from pathlib import Path
    config = Path('/etc/secrets/pico.env')
    if config.exists():
        from dotenv import load_dotenv
        load_dotenv(config, override=True)
    database = os.getenv('DATABASE_URL', '')
    if database.startswith(('postgres://', 'postgresql://')):
        os.environ.setdefault('PIPELINE_DATABASE_URL', database)
        from evidence_pipeline.bootstrap import bootstrap
        print(f'PICO seed records imported: {bootstrap(os.environ["PIPELINE_DATABASE_URL"])}', flush=True)
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    exit_code = 0
    try:
        for command in commands(os.environ): children.append(subprocess.Popen(command))
        print(f'Clarity services started: {len(children)}; durable worker requires PostgreSQL.', flush=True)
        while not stopping:
            if any(child.poll() is not None for child in children):
                exit_code = 1
                break
            time.sleep(.5)
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        deadline = time.monotonic() + 20
        for child in children:
            try: child.wait(timeout=max(0, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
    return exit_code

if __name__ == '__main__': sys.exit(main())
