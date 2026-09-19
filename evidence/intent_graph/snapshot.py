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
    """Every entity profile the website can route to, the library feed, and the built catalog.

    The catalog is the whole /api/library payload, not just its graph rows: building it takes about
    thirteen seconds on a cold process, which is longer than the browser waits, and a page that
    gives up shows fourteen curated profiles as though that were the library.
    """
    from . import store
    from evidence.library import build_library
    with store.session() as session:
        rows = store.graph_library()
        entities = {}
        for row in sorted(rows, key=lambda r: r['id']):
            payload = store.graph_entity(row['id'], session)
            if payload is not None:
                entities[row['id']] = payload
    catalog = build_library()
    return {'version': VERSION, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'entities': entities, 'library': rows, 'catalog': catalog}


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


def catalog():
    """The last published /api/library payload, or None. Never returned without its date."""
    data = load()
    published = (data or {}).get('catalog')
    if not published or not published.get('entries'):
        return None
    return dict(published, served_from='snapshot', published_at=(data or {}).get('generated_at'))


# The profiles worth shipping inside the web bundle. A cold engine is one thing; a container that
# is not running at all answers nothing, and no server-side snapshot can help then. These few are
# the pages a visitor is most likely to land on first.
BUNDLED = ('biomarker:il-18', 'biomarker:ca-125', 'biomarker:nfl', 'biomarker:psa', 'biomarker:apob',
           'variant:egfr-activating-mutation', 'precision_context:ret-selpercatinib')


def bundle(target):
    """Write the two files clarity-web serves when the API cannot be reached at all.

    library.json is the whole catalog, so the index never falls back to its fourteen curated rows.
    graph-profiles.json holds a handful of profiles, so a first landing is a page and not a
    skeleton. Both carry published_at, and the site labels them as published copies.
    """
    data = load() or {}
    catalog = data.get('catalog') or {}
    if not catalog.get('entries'):
        raise SystemExit('no published catalog to bundle; run --write first')
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    stamped = dict(catalog, served_from='snapshot', published_at=data.get('generated_at'))
    (target / 'library.json').write_text(json.dumps(stamped, ensure_ascii=False, separators=(',', ':')) + '\n')
    profiles = {k: v for k, v in (data.get('entities') or {}).items() if k in BUNDLED}
    (target / 'graph-profiles.json').write_text(json.dumps(
        {'version': VERSION, 'published_at': data.get('generated_at'), 'entities': profiles},
        ensure_ascii=False, separators=(',', ':')) + '\n')
    return {'library_entries': len(stamped['entries']), 'library_graph_rows': stamped.get('graph_rows'),
            'profiles': sorted(profiles), 'published_at': data.get('generated_at'),
            'bytes': {f.name: f.stat().st_size for f in (target / 'library.json', target / 'graph-profiles.json')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='rebuild the published snapshot')
    parser.add_argument('--bundle', metavar='DIR', help="write library.json and graph-profiles.json for the web bundle")
    args = parser.parse_args(argv)
    if args.bundle:
        if args.write:
            write()
        print(json.dumps(bundle(args.bundle), indent=1))
        return None
    data = write() if args.write else (load() or {})
    print(json.dumps({'version': data.get('version'), 'generated_at': data.get('generated_at'),
                      'entities': len(data.get('entities') or {}), 'library_rows': len(data.get('library') or []),
                      'catalog_entries': len((data.get('catalog') or {}).get('entries') or []),
                      'catalog_graph_rows': (data.get('catalog') or {}).get('graph_rows'),
                      'path': str(PATH), 'bytes': PATH.stat().st_size if PATH.exists() else 0}, indent=1))
    return data


if __name__ == '__main__':
    main()
