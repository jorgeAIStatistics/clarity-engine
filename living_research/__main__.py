import argparse
import json
import signal
import time
from pathlib import Path
from .store import Store
from .engine import Monitor, DEFAULTS, discover_targets
from .extraction import Extractor
from .workflow import review, publish, rebase


def main():
    parser=argparse.ArgumentParser(description='Clarity living research agent; all scientific domains, source-grounded review queue')
    parser.add_argument('--database',help='SQLite path or PostgreSQL DSN; defaults to configured environment')
    parser.add_argument('--config',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('targets',help='List all automatically discovered subjects without retrieving literature')
    run=commands.add_parser('run',help='Perform one bounded monitoring run')
    run.add_argument('--only',action='append',help='Target ID, repeatable (entity:apob, compound:creatine-monohydrate)')
    run.add_argument('--llm',action='store_true',help='Enable paid, quote-grounded extraction within configured call budget')
    watch=commands.add_parser('watch',help='Run the persistent scheduler until terminated')
    watch.add_argument('--llm',action='store_true')
    watch.add_argument('--poll-seconds',type=int,default=3600)
    commands.add_parser('status')
    listing=commands.add_parser('proposals');listing.add_argument('--status')
    for action in ('approve','reject'):
        p=commands.add_parser(action);p.add_argument('id');p.add_argument('--reviewer',required=True);p.add_argument('--note',required=True)
    for action in ('publish','rebase'):
        commands.add_parser(action).add_argument('id')
    args=parser.parse_args()
    config={**DEFAULTS,**(json.loads(args.config.read_text()) if args.config else {})}
    for key in ('initial_lookback_days','overlap_days','interval_days','max_targets','max_records','max_llm_calls','max_llm_calls_per_day'):
        if not isinstance(config[key],int) or isinstance(config[key],bool) or config[key]<1:parser.error(f'{key} must be a positive integer')
    if args.command=='targets':print(json.dumps(discover_targets(),indent=2));return
    store=Store(args.database)
    try:
        if args.command in ('run','watch'):
            stopped=False
            def stop(*_):
                nonlocal stopped
                stopped=True
            signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
            if args.command=='watch' and args.poll_seconds<60:parser.error('poll-seconds must be at least 60')
            while not stopped:
                if args.command=='watch':store.put('worker','scheduler',{'heartbeat':time.time(),'poll_seconds':args.poll_seconds,'llm_enabled':args.llm})
                extractor=Extractor(args.llm,config['max_llm_calls'])
                try:
                    result=Monitor(store,config,extractor=extractor).run(only=getattr(args,'only',None))
                    if args.command=='watch':store.put('worker','scheduler',{'heartbeat':time.time(),'poll_seconds':args.poll_seconds,'llm_enabled':args.llm,'last_run_status':result['status']})
                    print(json.dumps(result),flush=True)
                    if args.command=='run' and result['status']!='completed':raise SystemExit(1)
                except Exception as error:
                    if args.command=='run':raise
                    print(json.dumps({'status':'failed','error_type':type(error).__name__}),flush=True)
                if args.command=='run':break
                deadline=time.monotonic()+args.poll_seconds
                while not stopped and time.monotonic()<deadline:time.sleep(min(1,max(0,deadline-time.monotonic())))
        elif args.command=='status':print(json.dumps({'targets':len(store.all('target')),'runs':store.all('run')[:10],'proposals':len(store.all('proposal'))},indent=2))
        elif args.command=='proposals':print(json.dumps([p for p in store.all('proposal') if not args.status or p['status']==args.status],indent=2))
        elif args.command in ('approve','reject'):print(json.dumps(review(store,args.id,args.reviewer,args.note,args.command=='approve'),indent=2))
        elif args.command=='publish':print(json.dumps(publish(store,args.id),indent=2))
        elif args.command=='rebase':print(json.dumps(rebase(store,args.id),indent=2))
    finally:store.close()

if __name__=='__main__':main()
