"""M37 frozen suite (graphed-exec-local slice): exercise the worker/profiler code paths IN THE MAIN
PROCESS. In normal use these run inside spawned worker processes (where coverage.py cannot observe
them) or only when a profiler is attached; here we drive the same module functions directly and via
a ThreadExecutor, deterministically and on every platform (no subprocess-coverage machinery, no
dashboard dependency)."""

from __future__ import annotations

import pickle
import queue
import threading

from graphed_core import Partition, Plan, Task, TaskPhase
from graphed_debug import StageError
from graphed_debug.errors import SourceFrame
from probe import add, count_entries

import graphed_exec_local.executors as ex
from graphed_exec_local.executors import ThreadExecutor


class FakeProfiler:
    """A deterministic WorkerProfiler stand-in (no pyinstrument): flush always yields bytes."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def flush(self) -> bytes | None:
        return b"prof-bytes"

    def stop(self) -> bytes | None:
        self.stopped = True
        return b"prof-bytes"


def fake_factory() -> FakeProfiler:
    return FakeProfiler()


class ProfMonitor:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.profiles: list[tuple[str, bytes]] = []
        self._lock = threading.Lock()

    def on_task(self, event: object) -> None:
        with self._lock:
            self.events.append(event)

    def on_profile(self, worker: str, payload: bytes) -> None:
        with self._lock:
            self.profiles.append((worker, payload))

    def on_combine(self, leaves_done: int) -> None:
        pass

    def worker_profiler_factory(self):  # type: ignore[no-untyped-def]
        return fake_factory


def _reset_globals() -> None:
    ex._proc_resources = None
    ex._proc_event_q = None
    ex._proc_profiler = None
    ex._shared_objects.clear()
    with ex._profiler_lock:
        ex._live_profilers.clear()


def test_thread_profiling_runs_profiler_in_process() -> None:
    mon = ProfMonitor()
    tasks = [Task(k, Partition(f"f{k}.root", "Events", 0, (k + 1) * 3)) for k in range(4)]
    plan = Plan(process=count_entries, combine=add, empty=lambda: 0, tasks=tasks)
    with ThreadExecutor(max_workers=2, monitor=mon) as e:
        result = e.run(plan)
    assert result.value == sum((k + 1) * 3 for k in range(4))
    assert mon.profiles  # the fake profiler flushed -> on_profile fired (emit_profile path)
    assert sum(1 for ev in mon.events if ev.phase is TaskPhase.FINISHED) == 4  # type: ignore[attr-defined]


def test_render_error_branches() -> None:
    err = StageError(
        op="divide",
        frames=(SourceFrame(filename="a.py", lineno=7),),
        input_forms=(),
        partition="p",
        cause_type="ZeroDivisionError",
        cause_message="x",
        opt_level=1,
    )
    assert ex._render_error(err) == str(err)  # StageError -> its own source-mapped text
    assert ex._render_error(ValueError("z")) == "ValueError: z"  # generic fallback


def test_proc_emit_paths() -> None:
    try:
        q: queue.Queue = queue.Queue(maxsize=2)
        ex._proc_event_q = q
        ex._proc_emit(("task", "A"))
        assert q.get_nowait() == ("task", "A")
        ex._proc_emit(("x", 1))
        ex._proc_emit(("y", 2))
        ex._proc_emit(("z", 3))  # queue full -> dropped, never raises
        ex._proc_event_q = None
        ex._proc_emit(("ignored", 1))  # None queue -> no-op
    finally:
        _reset_globals()


def test_proc_init_and_worker_entry_in_process() -> None:
    try:
        q: queue.Queue = queue.Queue(maxsize=50)
        ex._proc_init(fake_factory, q)  # the process-pool initializer, with a profiler
        assert ex._proc_resources is not None
        assert ex._proc_profiler is not None
        token = "tok"
        ex._prime_shared(token, pickle.dumps(count_entries))  # the broadcast prime (worker side)
        assert token in ex._shared_objects
        out = ex._proc_task_shared(token, Task(0, Partition("f.root", "Events", 0, 9)))  # worker entry
        assert out == 9
        kinds = []
        while True:
            try:
                kinds.append(q.get_nowait()[0])
            except queue.Empty:
                break
        assert "task" in kinds and "profile" in kinds  # STARTED/FINISHED + a profiler flush
    finally:
        _reset_globals()


def test_register_and_stop_all_profilers() -> None:
    try:
        prof = FakeProfiler()
        ex._register_profiler(prof)
        ex._stop_all_profilers()
        assert prof.stopped
    finally:
        _reset_globals()
