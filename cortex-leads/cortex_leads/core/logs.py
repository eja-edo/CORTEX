"""One place that sets up logging for the long-running processes (worker, lessons, classroom, dev.local serve, bridges).

Records go through a queue: the caller only puts the record on it, and a background thread does the writing, so an event loop is
never held up by a slow stdout or journald. Level from `CL_LOG_LEVEL` (default INFO). Under systemd the lines land in journald,
which adds its own timestamp; the format still carries one so a plain terminal or a log file reads the same."""
import atexit
import logging
import logging.handlers
import os
import queue
import sys

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_listener: logging.handlers.QueueListener | None = None


def setup_logging(level: str | None = None) -> None:
    """Idempotent: a second call only changes the level."""
    global _listener
    root = logging.getLogger()
    root.setLevel((level or os.environ.get("CL_LOG_LEVEL") or "INFO").upper())
    if _listener is not None:
        return
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(logging.Formatter(FORMAT))
    q: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    for h in list(root.handlers):  # a basicConfig done earlier would print every line twice
        root.removeHandler(h)
    root.addHandler(logging.handlers.QueueHandler(q))
    _listener = logging.handlers.QueueListener(q, out, respect_handler_level=True)
    _listener.start()
    atexit.register(_listener.stop)  # flush what is still queued when the process ends
    for noisy in ("httpx", "httpcore"):  # one line per HTTP call, and URLs can carry a token (Pancake): only warnings
        logging.getLogger(noisy).setLevel(logging.WARNING)
