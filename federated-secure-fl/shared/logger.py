import logging, json, os, sys, uuid, time
from datetime import datetime, timezone
from pathlib import Path


class JSONLineHandler(logging.Handler):
    def __init__(self, filepath: Path):
        super().__init__()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(filepath, "a", buffering=1)

    def emit(self, record):
        entry = {
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "level":          record.levelname,
            "service":        record.name,
            "event":          record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            **getattr(record, "data", {}),
        }
        self._file.write(json.dumps(entry) + "\n")

    def close(self):
        self._file.close()
        super().close()


def get_logger(service_name: str) -> logging.Logger:
    run_id  = os.getenv("RUN_ID", "default")
    log_dir = Path(os.getenv("LOG_DIR", "/app/logs")) / f"run_{run_id}"

    logger = logging.getLogger(service_name)
    if logger.handlers:
        return logger   # already initialised — avoid duplicate handlers
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.addHandler(JSONLineHandler(log_dir / f"{service_name}.jsonl"))

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(
        f"%(asctime)s [{service_name}] %(levelname)s %(message)s"
    ))
    logger.addHandler(stream)
    return logger


def log_event(logger: logging.Logger, event: str,
              correlation_id: str = None, **kwargs):
    record = logging.LogRecord(
        name=logger.name, level=logging.INFO,
        pathname="", lineno=0, msg=event, args=(), exc_info=None
    )
    record.data = kwargs
    record.correlation_id = correlation_id or str(uuid.uuid4())
    logger.handle(record)


class Timer:
    """Context manager for measuring duration_ms."""
    def __enter__(self):
        self._start = time.monotonic()
        return self
    def __exit__(self, *_):
        self.duration_ms = round((time.monotonic() - self._start) * 1000, 2)
