#!/usr/bin/env python3
import json, sys
from pathlib import Path

run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("experiment_logs/security_audit_20260509/run_a_redux")
trust_path = run_dir / "trust.jsonl"
server_path = run_dir / "server.jsonl"

events = [json.loads(l) for l in trust_path.read_text().splitlines() if l.strip()]
clients = {}
for e in events:
    cid = e.get("client_id")
    if cid not in clients:
        clients[cid] = {"anomaly_rounds": [], "final_trust": None}
    if e.get("is_anomaly"):
        clients[cid]["anomaly_rounds"].append(e.get("fl_round"))
    clients[cid]["final_trust"] = e.get("trust_score")

print("=== Trust Results ===")
for cid, d in sorted(clients.items(), key=lambda x: x[0] or ""):
    anomalies = d["anomaly_rounds"]
    trust = d["final_trust"]
    if trust is None:
        status = "N/A"
        print(f"  {str(cid):20s}  final=None    N/A   anomaly_rounds={anomalies}")
        continue
    status = "GREEN" if trust >= 0.90 else ("AMBER" if trust >= 0.60 else "RED")
    print(f"  {str(cid):20s}  final={trust:.4f}  {status}  anomaly_rounds={anomalies}")

print("\n=== Exclusion Events (from server.jsonl) ===")
sevents = [json.loads(l) for l in server_path.read_text().splitlines() if l.strip()]
excluded_by_round = {}
for e in sevents:
    if e.get("event") == "round_complete":
        r = e.get("round")
        excl = e.get("excluded_from_aggregation", [])
        if excl:
            excluded_by_round[r] = excl
print(f"  Rounds with exclusions: {sorted(excluded_by_round.keys())}")
for r, ids in sorted(excluded_by_round.items()):
    print(f"    Round {r:2d}: {ids}")
