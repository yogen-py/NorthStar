"""Assurance Reporting Router — Phase 6"""
import glob, json, os
from pathlib import Path
from fastapi import APIRouter
from shared.logger import get_logger, log_event

router = APIRouter(prefix="/assurance")
log = get_logger("assurance")
LOG_BASE = os.getenv("LOG_DIR", "/app/logs")


def _latest_run_dir() -> Path | None:
    dirs = sorted(glob.glob(f"{LOG_BASE}/run_*/"), key=os.path.getmtime, reverse=True)
    return Path(dirs[0]) if dirs else None


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    events = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return events


def _build_report(run_dir: Path) -> dict:
    manifest = {}
    mp = run_dir / "_manifest.json"
    if mp.exists():
        try:
            manifest = json.loads(mp.read_text())
        except Exception:
            pass

    server_events     = _load_jsonl(run_dir / "server.jsonl")
    middleware_events = _load_jsonl(run_dir / "middleware.jsonl")
    trust_events      = _load_jsonl(run_dir / "trust.jsonl")

    admit_events       = [e for e in middleware_events if e.get("event") == "admit_decision"]
    admissions_allowed = [e for e in admit_events if e.get("result") == "allowed"]
    admissions_denied  = [e for e in admit_events if e.get("result") == "rejected"]
    policy_errors      = [e for e in middleware_events if e.get("event") == "policy_check_error"]

    round_events   = [e for e in server_events if e.get("event") == "round_complete"]
    gate_decisions = [e for e in server_events if e.get("event") == "round_gate_decision"]
    trust_updates  = [e for e in trust_events  if e.get("event") == "trust_updated"]
    anomalies      = [e for e in trust_updates  if e.get("is_anomaly") is True]

    clients: dict = {}
    for e in trust_updates:
        cid = e.get("client_id", "unknown")
        if cid not in clients:
            clients[cid] = {"client_id": cid, "initial_trust": e.get("T_prev"),
                            "final_trust": e.get("trust_score"),
                            "anomaly_count": 0, "rounds_participated": 0}
        clients[cid]["final_trust"] = e.get("trust_score")
        clients[cid]["rounds_participated"] += 1
        if e.get("is_anomaly"):
            clients[cid]["anomaly_count"] += 1

    flags: list = []
    for e in admissions_denied:
        flags.append({"type": "POLICY_DENIAL", "client_id": e.get("client_id"),
                      "round": e.get("round"), "reason": e.get("rejection_reason"),
                      "timestamp": e.get("timestamp")})
    for e in anomalies:
        flags.append({"type": "TRUST_ANOMALY", "client_id": e.get("client_id"),
                      "round": e.get("fl_round"), "update_norm": e.get("update_norm"),
                      "trust_after": e.get("trust_score"), "timestamp": e.get("timestamp")})
    for e in gate_decisions:
        d = e.get("decision", "")
        if d in ("reject", "stop"):
            flags.append({"type": f"OPERATOR_{d.upper()}", "round": e.get("round"),
                          "aggregated_loss": e.get("aggregated_loss"),
                          "timestamp": e.get("timestamp")})
    flags.sort(key=lambda f: f.get("timestamp") or "")
    flag_types = [f["type"] for f in flags]
    by_type = {t: flag_types.count(t) for t in sorted(set(flag_types))}

    return {
        "run_id": manifest.get("run_id", run_dir.name),
        "run_dir": str(run_dir),
        "trust_weighting": manifest.get("trust_weighting"),
        "total_rounds": len(round_events),
        "identity": {"total_admission_attempts": len(admit_events),
                     "allowed": len(admissions_allowed), "denied": len(admissions_denied),
                     "policy_errors": len(policy_errors)},
        "trust": {"anomalies_detected": len(anomalies), "clients": list(clients.values())},
        "rounds": round_events,
        "operator_decisions": gate_decisions,
        "compliance_flags": flags,
        "compliance_summary": {"total_flags": len(flags), "by_type": by_type},
    }


@router.get("/report")
def get_report(run_id: str | None = None):
    """Return structured assurance report. Defaults to most-recent run."""
    if run_id:
        run_dir = Path(LOG_BASE) / f"run_{run_id}"
    else:
        run_dir = _latest_run_dir()

    if not run_dir or not run_dir.exists():
        return {"error": "No completed run found", "log_base": LOG_BASE}

    report = _build_report(run_dir)
    log_event(log, "assurance_report_generated",
              run_id=report["run_id"],
              total_flags=report["compliance_summary"]["total_flags"],
              anomalies=report["trust"]["anomalies_detected"])
    return report
