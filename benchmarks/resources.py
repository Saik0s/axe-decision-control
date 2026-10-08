"""Optional whole-process resource sampling for an explicitly selected server PID.

RSS is measured in KiB, not per-request or Metal allocation peaks. CPU percent
comes from ps and is not a calibrated energy measurement.
"""

from __future__ import annotations

import math
import subprocess
import threading
import time
from typing import Annotated, Literal

from pydantic import Field

from axe_control.decisions import Count, Nonnegative, StrictModel

_INTERVAL_SECONDS = 0.1
_PS_TIMEOUT_SECONDS = 0.5
_JOIN_TIMEOUT_SECONDS = 1.0


class ResourceSample(StrictModel):
    t_seconds: Nonnegative
    rss_kib: Count
    cpu_percent: Nonnegative


class ResourceReport(StrictModel):
    pid: Annotated[int, Field(gt=0)]
    scope: Literal["whole_process"] = "whole_process"
    interval_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = _INTERVAL_SECONDS
    samples: list[ResourceSample] = Field(default_factory=list)
    peak_rss_kib: Count | None = None
    errors: list[str] = Field(default_factory=list)
    cpu_note: str = (
        "CPU percent is reported by ps for the whole process; "
        "it is not calibrated energy or per-request CPU usage."
    )


class _SamplingError(RuntimeError):
    """A fixed diagnostic that contains no subprocess output or environment data."""


def _read_sample(pid: int, started_at: float) -> ResourceSample:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=,pcpu=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=_PS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise _SamplingError("Resource sampling timed out.") from None
    except (OSError, UnicodeError):
        raise _SamplingError("Resource sampling could not execute ps.") from None

    if result.returncode != 0 or not result.stdout.strip():
        raise _SamplingError("Resource sampling could not read the selected PID.") from None

    rows = result.stdout.strip().splitlines()
    fields = rows[0].split()
    if len(rows) != 1 or len(fields) != 2:
        raise _SamplingError("Resource sampling returned invalid metrics.") from None
    try:
        rss_kib = int(fields[0])
        cpu_percent = float(fields[1])
    except (ValueError, OverflowError):
        raise _SamplingError("Resource sampling returned invalid metrics.") from None
    if rss_kib < 0 or cpu_percent < 0 or not math.isfinite(cpu_percent):
        raise _SamplingError("Resource sampling returned invalid metrics.") from None

    return ResourceSample(
        t_seconds=time.monotonic() - started_at,
        rss_kib=rss_kib,
        cpu_percent=cpu_percent,
    )


class ProcessSampler:
    """Collect an initial verified sample, then sample in a bounded background loop.

    A background sampling failure ends collection and preserves earlier samples.
    stop() is repeatable and never waits indefinitely for ps or the worker thread.
    """

    def __init__(self, pid: int) -> None:
        if type(pid) is not int or pid <= 0:
            raise ValueError("Resource sampling requires an explicit positive integer PID.")
        self._pid = pid
        self._samples: list[ResourceSample] = []
        self._errors: list[str] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Resource sampler has already been started.")
            started_at = time.monotonic()
            initial_sample = _read_sample(self._pid, started_at)
            thread = threading.Thread(
                target=self._collect,
                args=(started_at,),
                name="axe-resource-sampler",
                daemon=True,
            )
            try:
                thread.start()
            except RuntimeError:
                raise RuntimeError("Resource sampler could not start its thread.") from None
            self._samples.append(initial_sample)
            self._thread = thread

    def _collect(self, started_at: float) -> None:
        next_sample_at = time.monotonic() + _INTERVAL_SECONDS
        while not self._stop_event.wait(max(0.0, next_sample_at - time.monotonic())):
            try:
                sample = _read_sample(self._pid, started_at)
            except _SamplingError as error:
                with self._lock:
                    self._errors.append(str(error))
                return
            with self._lock:
                if self._stop_event.is_set():
                    return
                self._samples.append(sample)
            next_sample_at += _INTERVAL_SECONDS
            now = time.monotonic()
            # Skip missed deadlines instead of issuing a burst of ps calls.
            if next_sample_at <= now:
                next_sample_at = now + _INTERVAL_SECONDS

    def stop(self) -> ResourceReport:
        with self._lock:
            thread = self._thread
            if thread is None:
                raise RuntimeError("Resource sampler has not been started.")
            self._stop_event.set()
        thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            if thread.is_alive():
                message = "Resource sampler did not stop within the timeout."
                if message not in self._errors:
                    self._errors.append(message)
            samples = [sample.model_copy() for sample in self._samples]
            errors = list(self._errors)
        return ResourceReport(
            pid=self._pid,
            samples=samples,
            peak_rss_kib=max((sample.rss_kib for sample in samples), default=None),
            errors=errors,
        )
