"""Supervise the API and bounded research scheduler on the existing Render service.

No threads inside Gunicorn, no in-memory checkpoints, and no extra paid service.
Render restarts this parent if either required child exits unexpectedly.
"""
import os
import signal
import subprocess
import sys
import time


def database_url(env):
    return env.get('CLARITY_RESEARCH_DATABASE_URL') or env.get('DATABASE_URL', '')


def postgres_reachable(url, connect=None, timeout=5):
    """Does the database actually answer?

    A URL that merely looks like Postgres is not a database. On 13 October the Render Postgres
    instance stopped resolving, the seed import below raised, and the whole service exited 1 —
    taking the API down with it, although the API never touches Postgres. This is the check that
    tells an outage apart from a misconfiguration.
    """
    if not str(url).startswith(('postgres://', 'postgresql://')):
        return False
    try:
        if connect is None:
            import psycopg
            connect = psycopg.connect
        with connect(url, connect_timeout=timeout) as connection:
            connection.execute('SELECT 1')
        return True
    except Exception as error:
        print(f'PostgreSQL is not reachable, so the research pipeline stays down: '
              f'{type(error).__name__}: {error}', flush=True)
        return False


def commands(env, database_ready=None):
    result = [[sys.executable, '-m', 'gunicorn', 'app:app', '--bind', f"0.0.0.0:{env.get('PORT', '8000')}",
               '--timeout', '120', '--workers', '1', '--threads', '4']]
    database = database_url(env)
    # A child that needs the database is only started when the database answered. Starting one
    # anyway means it exits immediately, and the supervisor treats any child exiting as fatal.
    usable = database.startswith(('postgres://', 'postgresql://')) if database_ready is None else bool(database_ready)
    if env.get('CLARITY_RESEARCH_ENABLED', '1') == '1' and usable:
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
        # Configured correctly but unreachable is an outage: serve what we can and say what is off.
        if usable:
            result.append([sys.executable, '-m', 'evidence_pipeline.worker'])
        else:
            print('PICO worker not started: its database did not answer.', flush=True)
    return result


def main():
    from pathlib import Path
    config = Path('/etc/secrets/pico.env')
    if config.exists():
        from dotenv import load_dotenv
        load_dotenv(config, override=True)
    database = database_url(os.environ)
    ready = postgres_reachable(database)
    if ready:
        os.environ.setdefault('PIPELINE_DATABASE_URL', database)
        from evidence_pipeline.bootstrap import bootstrap
        try:
            print(f'PICO seed records imported: {bootstrap(os.environ["PIPELINE_DATABASE_URL"])}', flush=True)
        except Exception as error:
            # The seed import is not on the serving path. It must never be the reason the evidence
            # API fails to start.
            ready = False
            print(f'PICO seed import failed, so the research pipeline stays down: '
                  f'{type(error).__name__}: {error}', flush=True)
    elif database:
        print('Starting the evidence API without the research pipeline. The catalog, the library '
              'and every profile are served from Neo4j and the published snapshot, neither of '
              'which needs PostgreSQL.', flush=True)
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    exit_code = 0
    try:
        for command in commands(os.environ, database_ready=ready): children.append(subprocess.Popen(command))
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
