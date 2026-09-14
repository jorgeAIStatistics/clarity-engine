"""Export a validated catalog to the separately deployed frontend repository.
Usage: python3 -m evidence.export_catalog ../clarity-web/src/evidence/catalog.json
"""
import json
import sys
from pathlib import Path
from .service import CATALOG, validate_catalog

if __name__=='__main__':
    validate_catalog(CATALOG)
    from .provenance import validate_enrichment
    validate_enrichment(CATALOG,json.loads(Path(__file__).with_name("source_snapshot.json").read_text()))
    Path(sys.argv[1]).write_text(json.dumps(CATALOG,indent=2,ensure_ascii=False)+'\n')

    destination=Path(sys.argv[1])
    destination.with_name('catalog-index.json').write_text(json.dumps({'entities':[{k:e.get(k) for k in ('id','name','aliases','summary','entity_type')} for e in CATALOG['entities']]},ensure_ascii=False,separators=(',',':'))+'\n')
    destination.with_name('frameworks.json').write_text(json.dumps({'frameworks':CATALOG['frameworks']},ensure_ascii=False,separators=(',',':'))+'\n')

    from .enrichment import OVERLAYS
    (destination.parent.parent.parent/'public'/'intervention-enrichment.json').write_text(json.dumps(OVERLAYS,ensure_ascii=False,separators=(',',':'))+'\n')
    from .visual_report import build_reports
    import os
    public=destination.parent.parent.parent/'public'/'visual-evidence.json'
    temporary=public.with_suffix('.tmp')
    temporary.write_text(json.dumps(build_reports(),ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
    os.replace(temporary,public)
