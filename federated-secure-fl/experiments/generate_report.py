#!/usr/bin/env python3
"""
experiments/generate_report.py — Phase 6 Assurance Report Generator

Usage:
    python3 experiments/generate_report.py [path/to/run_dir]
    python3 experiments/generate_report.py          # most-recent run

Produces <run_dir>/report.html — self-contained, no CDN dependencies.
"""
import glob, json, os, sys
from pathlib import Path
from datetime import datetime, timezone

# ───────────────────────── Data loading ──────────────────────────

def _latest_run_dir(log_base: str = "logs") -> Path | None:
    dirs = sorted(glob.glob(f"{log_base}/run_*/"), key=os.path.getmtime, reverse=True)
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


def _build_data(run_dir: Path) -> dict:
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
    gate_by_round  = {e.get("round"): e.get("decision") for e in gate_decisions}

    trust_updates = [e for e in trust_events if e.get("event") == "trust_updated"]
    anomalies     = [e for e in trust_updates if e.get("is_anomaly") is True]

    clients: dict = {}
    for e in trust_updates:
        cid = e.get("client_id", "unknown")
        if cid not in clients:
            clients[cid] = {"client_id": cid, "initial_trust": e.get("T_prev"),
                            "final_trust": e.get("trust_score"),
                            "anomaly_count": 0, "rounds_participated": 0,
                            "rounds": []}
        clients[cid]["final_trust"] = e.get("trust_score")
        clients[cid]["rounds_participated"] += 1
        if e.get("is_anomaly"):
            clients[cid]["anomaly_count"] += 1
        clients[cid]["rounds"].append(e)

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
        "manifest": manifest,
        "run_id": manifest.get("run_id", run_dir.name),
        "trust_weighting": manifest.get("trust_weighting"),
        "round_events": round_events,
        "gate_by_round": gate_by_round,
        "admit_events": admit_events,
        "admissions_allowed": admissions_allowed,
        "admissions_denied": admissions_denied,
        "policy_errors": policy_errors,
        "trust_updates": trust_updates,
        "anomalies": anomalies,
        "clients": clients,
        "flags": flags,
        "by_type": by_type,
    }


# ───────────────────────── HTML helpers ──────────────────────────

def _esc(v) -> str:
    if v is None:
        return "<span class='na'>—</span>"
    s = str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_norm(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
        if f >= 1e15:
            return f"{f:.2e}"
        return f"{f:,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _badge(flag_type: str) -> str:
    colors = {
        "POLICY_DENIAL": "var(--badge-orange)",
        "TRUST_ANOMALY":  "var(--badge-red)",
    }
    color = colors.get(flag_type, "var(--badge-blue)")
    return f'<span class="badge" style="background:{color}">{_esc(flag_type)}</span>'


def _trust_color(score) -> str:
    if score is None:
        return "var(--card-neutral)"
    try:
        f = float(score)
        if f >= 0.8:
            return "var(--card-green)"
        if f >= 0.6:
            return "var(--card-amber)"
        return "var(--card-red)"
    except (TypeError, ValueError):
        return "var(--card-neutral)"


# ───────────────────────── Section renderers ─────────────────────

def _section_header(data: dict) -> str:
    tw = data["trust_weighting"]
    tw_label = ("✅ Enabled" if tw is True else
                "❌ Disabled" if tw is False else
                f"{_esc(tw)}" if tw is not None else "—")
    manifest = data["manifest"]
    rows = ""
    for k, v in manifest.items():
        rows += f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""
<section id="run-header">
  <h2>Run Summary</h2>
  <div class="kv-grid">
    <div class="kv"><span class="kv-key">Run ID</span><span class="kv-val">{_esc(data['run_id'])}</span></div>
    <div class="kv"><span class="kv-key">Total Rounds</span><span class="kv-val">{len(data['round_events'])}</span></div>
    <div class="kv"><span class="kv-key">Trust Weighting</span><span class="kv-val">{tw_label}</span></div>
    <div class="kv"><span class="kv-key">Anomalies Detected</span><span class="kv-val">{len(data['anomalies'])}</span></div>
    <div class="kv"><span class="kv-key">Report Generated</span><span class="kv-val">{generated_at}</span></div>
  </div>
  <details><summary>Manifest fields</summary>
  <table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>
  </details>
</section>"""


def _section_compliance(data: dict) -> str:
    flags = data["flags"]
    by_type = data["by_type"]

    badges_html = " ".join(
        f'{_badge(t)} <span class="badge-count">×{n}</span>'
        for t, n in by_type.items()
    ) if by_type else "<em>No flags</em>"

    rows = ""
    for f in flags:
        rows += (
            f"<tr>"
            f"<td>{_badge(f['type'])}</td>"
            f"<td>{_esc(f.get('round', '—'))}</td>"
            f"<td>{_esc(f.get('client_id', '—'))}</td>"
            f"<td>{_esc(f.get('reason') or f.get('trust_after') or f.get('aggregated_loss') or '—')}</td>"
            f"<td class='ts'>{(_esc(f.get('timestamp', '')) or '—')[:19]}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='5' class='na'>No compliance flags recorded</td></tr>"

    return f"""
<section id="compliance">
  <h2>Compliance Summary</h2>
  <p><strong>Total flags:</strong> {len(flags)}</p>
  <div class="badge-row">{badges_html}</div>
  <h3>Flag Timeline</h3>
  <table>
    <thead><tr><th>Type</th><th>Round</th><th>Client</th><th>Detail</th><th>Timestamp</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _section_identity(data: dict) -> str:
    rows = ""
    for e in data["admit_events"]:
        result = e.get("result", "")
        css = "ok" if result == "allowed" else "err"
        rows += (
            f"<tr>"
            f"<td>{_esc(e.get('round', '—'))}</td>"
            f"<td>{_esc(e.get('client_id', '—'))}</td>"
            f"<td class='{css}'>{_esc(result)}</td>"
            f"<td>{_esc(e.get('rejection_reason', '—'))}</td>"
            f"<td>{_esc(e.get('policy_checked', '—'))}</td>"
            f"<td>{_esc(e.get('duration_ms', '—'))}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='6' class='na'>No admission events recorded (middleware may be inactive)</td></tr>"

    return f"""
<section id="identity">
  <h2>Identity &amp; Policy</h2>
  <div class="kv-grid">
    <div class="kv"><span class="kv-key">Total Attempts</span><span class="kv-val">{len(data['admit_events'])}</span></div>
    <div class="kv"><span class="kv-key">Allowed</span><span class="kv-val ok">{len(data['admissions_allowed'])}</span></div>
    <div class="kv"><span class="kv-key">Denied</span><span class="kv-val err">{len(data['admissions_denied'])}</span></div>
    <div class="kv"><span class="kv-key">Policy Errors</span><span class="kv-val">{len(data['policy_errors'])}</span></div>
  </div>
  <table>
    <thead><tr><th>Round</th><th>Client</th><th>Result</th><th>Rejection Reason</th><th>Policy</th><th>Duration ms</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _section_trust_trajectory(data: dict) -> str:
    rows = ""
    for e in data["trust_updates"]:
        t_prev = e.get("T_prev")
        t_new  = e.get("trust_score")
        try:
            delta = round(float(t_new) - float(t_prev), 4)
            delta_s = f"+{delta}" if delta >= 0 else str(delta)
            delta_css = "ok" if delta > 0 else ("err" if delta < 0 else "")
        except (TypeError, ValueError):
            delta_s, delta_css = "—", ""

        anom = e.get("is_anomaly", False)
        anom_s = '<span class="err">⚠ yes</span>' if anom else "no"
        rows += (
            f"<tr{'  class=\"anom-row\"' if anom else ''}>"
            f"<td>{_esc(e.get('fl_round', '—'))}</td>"
            f"<td>{_esc(e.get('client_id', '—'))}</td>"
            f"<td>{_esc(t_prev)}</td>"
            f"<td>{_esc(t_new)}</td>"
            f"<td class='{delta_css}'>{delta_s}</td>"
            f"<td>{_fmt_norm(e.get('update_norm'))}</td>"
            f"<td>{anom_s}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='7' class='na'>No trust events recorded</td></tr>"

    return f"""
<section id="trust-trajectory">
  <h2>Trust Trajectory</h2>
  <table>
    <thead><tr><th>Round</th><th>Client</th><th>T_prev</th><th>T_new</th><th>Δ</th><th>Update Norm</th><th>Anomaly</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _section_client_cards(data: dict) -> str:
    cards = ""
    for cid, c in data["clients"].items():
        ft = c.get("final_trust")
        color = _trust_color(ft)
        ft_s  = f"{float(ft):.3f}" if ft is not None else "—"
        it_s  = f"{float(c['initial_trust']):.3f}" if c.get("initial_trust") is not None else "—"
        cards += f"""
<div class="card" style="border-left:4px solid {color}">
  <div class="card-title">{_esc(cid)}</div>
  <div class="card-kv"><span>Initial trust</span><span>{it_s}</span></div>
  <div class="card-kv"><span>Final trust</span><span style="color:{color};font-weight:600">{ft_s}</span></div>
  <div class="card-kv"><span>Rounds participated</span><span>{c.get('rounds_participated', 0)}</span></div>
  <div class="card-kv"><span>Anomalies</span><span class="{'err' if c.get('anomaly_count',0)>0 else ''}">{c.get('anomaly_count', 0)}</span></div>
</div>"""

    if not cards:
        cards = "<p class='na'>No client trust data recorded.</p>"
    return f"""
<section id="clients">
  <h2>Per-Client Summary</h2>
  <div class="card-grid">{cards}</div>
  <p class="legend">
    <span style="color:var(--card-green)">■</span> ≥ 0.8 &nbsp;
    <span style="color:var(--card-amber)">■</span> 0.6 – 0.8 &nbsp;
    <span style="color:var(--card-red)">■</span> &lt; 0.6
  </p>
</section>"""


def _section_rounds(data: dict) -> str:
    rows = ""
    gate_by_round = data["gate_by_round"]
    for e in data["round_events"]:
        r   = e.get("round")
        dec = gate_by_round.get(r, "approve")
        dec_css = "" if dec == "approve" else "err"
        rows += (
            f"<tr>"
            f"<td>{_esc(r)}</td>"
            f"<td>{_esc(e.get('aggregated_loss'))}</td>"
            f"<td>{_esc(e.get('num_clients'))}</td>"
            f"<td class='{dec_css}'>{_esc(dec)}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='4' class='na'>No round data recorded</td></tr>"
    return f"""
<section id="rounds">
  <h2>Round Summary</h2>
  <table>
    <thead><tr><th>Round</th><th>Aggregated Loss</th><th>Clients</th><th>Gate Decision</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _section_scope() -> str:
    return """
<section id="scope-note">
  <h2>Scope Note</h2>
  <blockquote>
    Trust mechanics verified on mocked clients.
    Loss divergence between defended/undefended runs requires real gradient training.
    The trust engine and aggregation strategy are model-agnostic and require no
    changes to integrate real PyTorch clients.
  </blockquote>
</section>"""


# ───────────────────────── CSS ───────────────────────────────────

CSS = """
:root {
  --bg: #f8f9fa; --surface: #ffffff; --border: #dee2e6;
  --text: #212529; --text-muted: #6c757d;
  --badge-red: #dc3545; --badge-orange: #fd7e14; --badge-blue: #0d6efd;
  --card-green: #198754; --card-amber: #fd7e14; --card-red: #dc3545;
  --card-neutral: #6c757d;
  --ok: #198754; --err: #dc3545;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111317; --surface: #1e2125; --border: #373b3e;
    --text: #dee2e6; --text-muted: #9ea7b0;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; }
header { background: var(--surface); border-bottom: 1px solid var(--border);
         padding: 1.25rem 2rem; }
header h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.01em; }
header p  { color: var(--text-muted); font-size: 0.85rem; margin-top: 0.2rem; }
main { max-width: 1100px; margin: 0 auto; padding: 1.5rem 2rem 4rem; }
section { background: var(--surface); border: 1px solid var(--border);
          border-radius: 6px; padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; }
h2 { font-size: 1rem; font-weight: 700; margin-bottom: 1rem;
     padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
h3 { font-size: 0.9rem; font-weight: 600; margin: 1rem 0 0.5rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; padding: 0.4rem 0.6rem; font-size: 0.75rem;
     text-transform: uppercase; letter-spacing: 0.04em;
     color: var(--text-muted); border-bottom: 2px solid var(--border); }
td { padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
tr.anom-row { background: rgba(220,53,69,.06); }
.kv-grid { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; }
.kv { background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
      padding: 0.5rem 0.85rem; min-width: 160px; }
.kv-key { display: block; font-size: 0.7rem; text-transform: uppercase;
          letter-spacing: 0.05em; color: var(--text-muted); }
.kv-val { display: block; font-weight: 600; margin-top: 0.1rem; }
.badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 3px;
         color: #fff; font-size: 0.7rem; font-weight: 600; }
.badge-count { font-size: 0.8rem; color: var(--text-muted); margin-right: 0.5rem; }
.badge-row { margin-bottom: 1rem; }
.card-grid { display: flex; flex-wrap: wrap; gap: 1rem; }
.card { flex: 1 1 200px; background: var(--bg); border: 1px solid var(--border);
        border-radius: 6px; padding: 0.9rem 1rem; }
.card-title { font-weight: 700; margin-bottom: 0.6rem; }
.card-kv { display: flex; justify-content: space-between;
           font-size: 0.8rem; padding: 0.15rem 0; color: var(--text-muted); }
.card-kv span:last-child { color: var(--text); }
.legend { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.75rem; }
blockquote { border-left: 3px solid var(--border); padding-left: 1rem;
             color: var(--text-muted); font-style: italic; }
details { margin-top: 0.75rem; }
summary { cursor: pointer; font-size: 0.8rem; color: var(--text-muted); }
.ok  { color: var(--ok); }
.err { color: var(--err); }
.na  { color: var(--text-muted); }
.ts  { font-family: monospace; font-size: 0.75rem; }
"""


# ───────────────────────── HTML assembly ─────────────────────────

def _build_html(data: dict) -> str:
    tw = data["trust_weighting"]
    tw_s = "Trust Weighting ON" if tw is True else "Trust Weighting OFF" if tw is False else ""
    subtitle = f"{data['run_id']}" + (f" &nbsp;·&nbsp; {tw_s}" if tw_s else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assurance Report — {_esc(data['run_id'])}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Project North Star — Assurance Report</h1>
  <p>{subtitle}</p>
</header>
<main>
{_section_header(data)}
{_section_compliance(data)}
{_section_identity(data)}
{_section_trust_trajectory(data)}
{_section_client_cards(data)}
{_section_rounds(data)}
{_section_scope()}
</main>
</body>
</html>"""


# ───────────────────────── Entry point ───────────────────────────

def main():
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1]).resolve()
    else:
        cwd = Path.cwd()
        # Support running from both repo root and infra/
        log_base = cwd / "logs" if (cwd / "logs").exists() else cwd.parent / "logs"
        run_dir = _latest_run_dir(str(log_base))
        if run_dir is None:
            print("ERROR: No run directories found under logs/", file=sys.stderr)
            sys.exit(1)
        run_dir = run_dir.resolve()

    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating report for: {run_dir.name}")
    data = _build_data(run_dir)
    html = _build_html(data)
    out  = run_dir / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"✅ Report written: {out}")


if __name__ == "__main__":
    main()
