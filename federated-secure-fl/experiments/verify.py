import json, glob
for run in sorted(glob.glob('logs/run_*/server.jsonl'))[-2:]:
    print(run)
    for line in open(run):
        try:
            e = json.loads(line)
            if e.get('event') == 'round_complete':
                print(f'  Round {e["round"]}: loss={e.get("aggregated_loss")}')
        except: pass
