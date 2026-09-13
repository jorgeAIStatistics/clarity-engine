"""Export a validated catalog to the separately deployed frontend repository.
Usage: python3 -m evidence.export_catalog ../clarity-web/src/evidence/catalog.json
"""
import json
import sys
from pathlib import Path
from .service import CATALOG, validate_catalog

if __name__=='__main__':
    validate_catalog(CATALOG)
    Path(sys.argv[1]).write_text(json.dumps(CATALOG,indent=2,ensure_ascii=False)+'\n')
