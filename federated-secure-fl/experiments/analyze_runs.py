import json, glob, sys
from pathlib import Path

def load_jsonl(path):
    events = []
    if not path.exists():
        return events
    with open(path) as f:
        for line in f:
            try: events.append(json.loads(line))
            except: pass
    return events

def extract_round_metrics(run_dir):
    """Returns {round: {accuracy, aggregated_loss, malicious_weight}} per round."""
    server_log = Path(run_dir) / "server.jsonl"
    trust_log  = Path(run_dir) / "trust.jsonl"
    rounds = {}

    for e in load_jsonl(server_log):
        if e.get("event") == "round_complete":
            r = e["round"]
            if r not in rounds: rounds[r] = {}
            rounds[r]["aggregated_loss"] = e.get("aggregated_loss")
        if e.get("event") == "trust_weighting_applied":
            r = e["round"]
            if r not in rounds: rounds[r] = {}
            for c in e.get("clients", []):
                if c["client_id"] == "malicious_client":
                    rounds[r]["malicious_effective_n"] = c["effective_n"]
                    rounds[r]["malicious_trust"] = c["trust_score"]

    for e in load_jsonl(trust_log):
        if e.get("event") == "trust_updated":
            r = e.get("fl_round", e.get("round"))
            if r and r in rounds:
                if e.get("client_id") == "malicious_client":
                    rounds[r]["malicious_trust_after"] = e.get("trust_score", e.get("new_score"))

    return rounds

run_dirs = sorted(glob.glob("logs/run_*/"))
if len(run_dirs) < 2:
    print("Need at least 2 runs. Run experiments/run_attack_comparison.sh first.")
    sys.exit(1)

# Sort runs to ensure we get runA and runB in order if they were created consecutively
runA_dirs = sorted([d for d in run_dirs if "runA" in d])
runB_dirs = sorted([d for d in run_dirs if "runB" in d])

if runA_dirs and runB_dirs:
    run_a = runA_dirs[-1]
    run_b = runB_dirs[-1]
else:
    run_a = run_dirs[-2]
    run_b = run_dirs[-1]

print(f"\nRun A (undefended): {run_a}")
print(f"Run B (defended):   {run_b}\n")

metrics_a = extract_round_metrics(run_a)
metrics_b = extract_round_metrics(run_b)

print(f"{'Round':>6} | {'Loss A':>10} | {'Loss B':>10} | "
      f"{'Mal Trust B':>12} | {'Mal Weight B':>13}")
print("-" * 65)

for r in sorted(set(list(metrics_a.keys()) + list(metrics_b.keys()))):
    a = metrics_a.get(r, {})
    b = metrics_b.get(r, {})
    print(f"{r:>6} | "
          f"{a.get('aggregated_loss', '-'):>10} | "
          f"{b.get('aggregated_loss', '-'):>10} | "
          f"{b.get('malicious_trust_after', '-'):>12} | "
          f"{b.get('malicious_effective_n', '-'):>13}")
