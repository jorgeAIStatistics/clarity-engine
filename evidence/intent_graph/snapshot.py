"""A published copy of what the graph says, so a cold or unreachable engine still renders a page.

The engine reads Neo4j on every graph request. When the process is cold the first read costs about
three seconds, and when Neo4j is unreachable the route answers 503 — which is why the biomarkers
index could fall back to its fourteen curated profiles while ninety graph cards vanished, and why a
profile could sit on a wake screen.

This module writes that answer to a file at publish time and serves it when the live read fails or
runs long. A snapshot is never presented as live: every response it fills carries served_from and
the time it was published, and the page says so. Rebuild it whenever findings are published:

    python -m evidence.intent_graph.snapshot --write
"""
import argparse
import json
import os
import time
from pathlib import Path

PATH = Path(os.getenv('CLARITY_GRAPH_SNAPSHOT', str(Path(__file__).parent / 'snapshot.json')))
VERSION = 'graph-snapshot-v1'
_memory = {'loaded': False, 'data': None}


def build():
    """Every entity profile the website can route to, plus the library feed, read once."""
    from . import store
    with store.session() as session:
        rows = store.graph_library()
        entities = {}
        for row in sorted(rows, key=lambda r: r['id']):
            payload = store.graph_entity(row['id'], session)
            if payload is not None:
                entities[row['id']] = payload
    return {'version': VERSION, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'entities': entities, 'library': rows}


def write(path=None):
    target = Path(path or PATH)
    data = build()
    target.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    _memory.update(loaded=True, data=data)
    return data


def load():
    """The published snapshot, read once per process. A missing file is not an error."""
    if not _memory['loaded']:
        try:
            _memory['data'] = json.loads(PATH.read_text())
        except Exception:
            _memory['data'] = None
        _memory['loaded'] = True
    return _memory['data']


def published_at():
    data = load()
    return (data or {}).get('generated_at')


def entity(entity_id):
    data = load()
    return ((data or {}).get('entities') or {}).get(entity_id)


def library():
    data = load()
    return (data or {}).get('library') or []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='rebuild the published snapshot')
    args = parser.parse_args(argv)
    data = write() if args.write else (load() or {})
    print(json.dumps({'version': data.get('version'), 'generated_at': data.get('generated_at'),
                      'entities': len(data.get('entities') or {}), 'library_rows': len(data.get('library') or []),
                      'path': str(PATH), 'bytes': PATH.stat().st_size if PATH.exists() else 0}, indent=1))
    return data


if __name__ == '__main__':
    main()
