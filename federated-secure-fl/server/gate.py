import threading
import uvicorn
from fastapi import FastAPI
from shared.logger import get_logger, log_event

log = get_logger("gate")

class RoundGate:
    def __init__(self, enabled: bool = True, port: int = 9081):
        self.enabled = enabled
        self.port = port
        self._approval = threading.Event()
        self._decision = None
        self._current_summary = {}
        self._app = self._build_app()

    def _build_app(self):
        app = FastAPI()

        @app.get("/gate/status")
        def status():
            return {
                "waiting": not self._approval.is_set(),
                "summary": self._current_summary
            }

        @app.post("/gate/approve")
        def approve():
            self.submit("approve")
            return {"decision": "approve", "status": "round proceeding"}

        @app.post("/gate/reject")
        def reject():
            self.submit("reject")
            return {"decision": "reject", "status": "round discarded"}

        @app.post("/gate/stop")
        def stop():
            self.submit("stop")
            return {"decision": "stop", "status": "experiment stopping"}

        return app

    def start_http_server(self):
        """Run gate HTTP server on daemon thread."""
        def run():
            uvicorn.run(self._app, host="0.0.0.0", port=self.port,
                        log_level="warning")
        t = threading.Thread(target=run, daemon=True)
        t.start()

    def wait_for_approval(self, round_summary: dict) -> str:
        if not self.enabled:
            return "approve"
        self._approval.clear()
        self._current_summary = round_summary
        self._print_summary(round_summary)
        self._approval.wait()
        return self._decision

    def submit(self, decision: str):
        log_event(log, "operator_decision",
            decision=decision,
            round=self._current_summary.get("round"),
        )
        self._decision = decision
        self._approval.set()

    def _print_summary(self, s: dict):
        print("\n" + "═" * 55, flush=True)
        print(f"  ROUND {s['round']} COMPLETE — AWAITING YOUR APPROVAL",
              flush=True)
        print("═" * 55, flush=True)
        print(f"  {'Client':<15} {'Norm':>8}  {'Loss':>8}  {'Trust':>8}",
              flush=True)
        print("  " + "─" * 46, flush=True)
        for c in s.get("clients", []):
            print(f"  {c['client_id']:<15}"
                  f" {c['update_norm']:>8.4f}"
                  f" {c['train_loss']:>8.4f}"
                  f" {c['trust_score']:>8.4f}", flush=True)
        print("  " + "─" * 46, flush=True)
        print(f"  Aggregated loss : {s['aggregated_loss']:.6f}", flush=True)
        print("═" * 55, flush=True)
        print("  From your host terminal run ONE of:", flush=True)
        print("  curl -X POST http://localhost:9081/gate/approve",
              flush=True)
        print("  curl -X POST http://localhost:9081/gate/reject",
              flush=True)
        print("  curl -X POST http://localhost:9081/gate/stop",
              flush=True)
        print("═" * 55, flush=True)
