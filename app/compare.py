"""Run the comparator across two databases and emit results as SSE events.

The comparison runs in a worker thread. A progress callback counts rows scanned
per side and pushes `progress` events onto a queue; the FastAPI SSE generator
drains that queue and emits `progress` / `result` / `error` events to the client.
"""

import queue
import threading

from .comparator import compare
from .db import build_url, make_engine, stream_rows
from .schemas import ConnectionConfig

# Emit a progress event every N rows scanned per side.
PROGRESS_EVERY = 1000


class _Progress:
    def __init__(self, every: int = PROGRESS_EVERY):
        self.every = every
        self.source = 0
        self.target = 0
        self._last_source = 0
        self._last_target = 0

    def record_source(self) -> bool:
        self.source += 1
        return self.source - self._last_source >= self.every

    def record_target(self) -> bool:
        self.target += 1
        return self.target - self._last_target >= self.every

    def snapshot(self) -> dict:
        return {"source_scanned": self.source, "target_scanned": self.target}


def _emit(ev_q, kind, payload):
    try:
        ev_q.put((kind, payload), timeout=1)
    except queue.Full:
        # Client is reading too slowly; drop the event rather than block.
        pass


def compare_events(
    source_cfg: ConnectionConfig,
    target_cfg: ConnectionConfig,
    max_mismatch_size: int,
):
    """Generator yielding SSE text chunks for a comparison."""
    ev_q = queue.Queue()
    progress = _Progress()

    def _on_source():
        if progress.record_source():
            _emit(ev_q, "progress", progress.snapshot())

    def _on_target():
        if progress.record_target():
            _emit(ev_q, "progress", progress.snapshot())

    def worker(progress):
        source_engine = target_engine = None
        src_stream = tgt_stream = None
        try:
            source_engine = make_engine(build_url(source_cfg))
            target_engine = make_engine(build_url(target_cfg))

            src_stream = stream_rows(source_engine, source_cfg.query, _on_source)
            tgt_stream = stream_rows(target_engine, target_cfg.query, _on_target)

            source_mismatches, target_mismatches = compare(
                (r for r in src_stream),
                (r for r in tgt_stream),
                max_mismatch_size=max_mismatch_size,
            )

            payload = {
                "source_mismatches": [list(r) for r in source_mismatches],
                "target_mismatches": [list(r) for r in target_mismatches],
                "source_scanned": progress.source,
                "target_scanned": progress.target,
                "max_mismatch_size": max_mismatch_size,
                "truncated": (
                    len(source_mismatches) >= max_mismatch_size
                    or len(target_mismatches) >= max_mismatch_size
                ),
            }
            _emit(ev_q, "result", payload)
        except Exception as exc:  # noqa: BLE001 - report any failure to the client
            _emit(ev_q, "error", {"message": str(exc)})
        finally:
            for s in (src_stream, tgt_stream):
                try:
                    s.close()
                except Exception:
                    pass
            for eng in (source_engine, target_engine):
                try:
                    eng.dispose()
                except Exception:
                    pass

    threading.Thread(target=worker, args=(progress,), daemon=True).start()

    while True:
        try:
            kind, payload = ev_q.get(timeout=1.0)
        except queue.Empty:
            continue

        data = _dump(payload)
        if kind == "progress":
            yield f"event: progress\ndata: {data}\n\n"
        elif kind == "result":
            yield f"event: result\ndata: {data}\n\n"
            break
        elif kind == "error":
            yield f"event: error\ndata: {data}\n\n"
            break


def _dump(payload) -> str:
    import json

    return json.dumps(payload, default=str)
