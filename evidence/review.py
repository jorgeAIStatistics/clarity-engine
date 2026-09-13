"""Apply a documented, source-backed review to a catalog snapshot.

python3 -m evidence.review review.json --output /path/to/reviewed-catalog.json
The input must identify entity_id and dimension-keyed reviews. This command
writes a separate snapshot by default workflow; exporting/publishing is explicit.
"""
import argparse
import json
from pathlib import Path
from .service import CATALOG, get_entity, validate_catalog
from .appraisal import grade_entity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_file',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    review=json.loads(args.review_file.read_text())
    entity=get_entity(review['entity_id'])
    if entity is None: parser.error('Entity not found')
    result=grade_entity(entity,review['reviews'])
    entity['assessments']=result['assessments']
    reviewed=sum(a['rating']!='Not yet assessed' for a in entity['assessments'].values())
    entity['review_status']='reviewed' if reviewed==len(entity['assessments']) else 'partially_reviewed' if reviewed else 'reference_summary'
    data=json.loads(json.dumps(CATALOG))
    data['entities']=[entity if e['id']==entity['id'] else e for e in data['entities']]
    data['catalog_version']=review['catalog_version']
    validate_catalog(data)
    args.output.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')

if __name__=='__main__': main()
