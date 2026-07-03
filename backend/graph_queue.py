"""
Garuda — Graph Write Queue (graph_queue.py)

ADR-002: Structured In-Process Retry Queue for Knowledge Graph operations.

Problem: pipeline.py step 7 (graph writes) was wrapped in a bare
`except Exception: logger.warning(...)`. Any AstraDB timeout, rate limit,
or transient error silently orphaned entities from their graph nodes —
permanently, with no retry and no observability.

Solution: failed graph operations are pushed to a bounded in-memory queue.
A background daemon thread drains the queue with exponential backoff
(1 s → 4 s → 16 s, max 3 attempts). Items that exhaust retries are written
to the `ingestion_logs` AstraDB collection as dead-letter records.

Public API:
    enqueue(operations)        — push a list of (fn, args, kwargs, label) ops
    get_dead_letter_count()    — total dead-letter events since process start
    get_queue_depth()          — current items waiting to be executed
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

MAX_QUEUE_DEPTH = 1_000   # items; drop + dead-letter if exceeded
MAX_ATTEMPTS    = 3
_BACKOFF_SECS   = [1, 4, 16]   # wait before attempt 2, 3, (then dead-letter)

# ── Internal state ────────────────────────────────────────────────────────────

_dead_letter_count = 0
_dead_letter_lock  = threading.Lock()

_q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_DEPTH)


class _Op:
    """A single graph operation with retry state."""
    __slots__ = ("fn", "args", "kwargs", "label", "attempts")

    def __init__(self, fn: Callable, args: tuple, kwargs: dict, label: str):
        self.fn       = fn
        self.args     = args
        self.kwargs   = kwargs
        self.label    = label
        self.attempts = 0


# ── Public API ────────────────────────────────────────────────────────────────

def get_dead_letter_count() -> int:
    """Total graph operations that exhausted all retries since process start."""
    with _dead_letter_lock:
        return _dead_letter_count


def get_queue_depth() -> int:
    """Current number of operations waiting in the queue."""
    return _q.qsize()


def enqueue(operations: list[tuple[Callable, tuple, dict, str]]) -> None:
    """
    Push graph operations onto the retry queue.

    Each item is a 4-tuple:  (callable, args_tuple, kwargs_dict, label_str)
    Example:
        enqueue([
            (upsert_node, (entity_id, name, etype, etype), {}, f"node:{entity_id}"),
            (upsert_edge, (), {"source_id": a, "target_id": b, ...}, f"edge:{a}-{b}"),
        ])

    If the queue is full, the operation is dead-lettered immediately
    (to avoid blocking the pipeline thread).
    """
    for fn, args, kwargs, label in operations:
        op = _Op(fn, args, kwargs, label)
        try:
            _q.put_nowait(op)
        except queue.Full:
            logger.warning("graph_queue full — dead-lettering immediately: %s", label)
            _write_dead_letter(label, "queue_full_on_enqueue")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_dead_letter(label: str, reason: str) -> None:
    global _dead_letter_count
    with _dead_letter_lock:
        _dead_letter_count += 1

    try:
        from astra_client import get_db
        from datetime import datetime, timezone

        dlq_id = f"dlq-{int(time.time() * 1000)}-{threading.get_ident() % 99999:05d}"
        get_db().get_collection("ingestion_logs").insert_one({
            "_id":        dlq_id,
            "log_type":   "graph_dead_letter",
            "label":      label,
            "reason":     reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        # Dead-letter write itself failed — log to stderr, do not re-raise
        logger.error("graph_queue: failed to write dead-letter record for '%s': %s", label, exc)


def _drain_worker() -> None:
    """
    Background daemon that drains _q.
    Runs forever; killed automatically when the main process exits (daemon=True).
    """
    logger.info("graph_queue drain worker started")
    while True:
        # Block until an item arrives (timeout keeps the thread interruptible)
        try:
            op: _Op = _q.get(timeout=5)
        except queue.Empty:
            continue

        op.attempts += 1
        try:
            op.fn(*op.args, **op.kwargs)
            logger.debug("graph_queue OK: %s (attempt %d)", op.label, op.attempts)

        except Exception as exc:
            if op.attempts < MAX_ATTEMPTS:
                backoff = _BACKOFF_SECS[op.attempts - 1]
                logger.warning(
                    "graph_queue retry %d/%d in %ds: %s — %s",
                    op.attempts, MAX_ATTEMPTS, backoff, op.label, exc,
                )
                time.sleep(backoff)
                try:
                    _q.put_nowait(op)
                except queue.Full:
                    logger.error(
                        "graph_queue full on retry — dead-lettering: %s", op.label
                    )
                    _write_dead_letter(op.label, f"queue_full_on_retry after {op.attempts} attempts: {exc}")
            else:
                logger.error(
                    "graph_queue exhausted retries (%d) for: %s — %s",
                    MAX_ATTEMPTS, op.label, exc,
                )
                _write_dead_letter(op.label, f"max_retries_exceeded: {exc}")

        finally:
            _q.task_done()


# ── Start drain daemon ────────────────────────────────────────────────────────

_drain_thread = threading.Thread(
    target=_drain_worker,
    daemon=True,
    name="garuda-graph-queue",
)
_drain_thread.start()
