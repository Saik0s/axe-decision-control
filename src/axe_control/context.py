"""Shared request limits and cancellation for every control policy."""

from __future__ import annotations

import threading
import time

from .decisions import DecisionReply, DecisionRequest
from .models import ActionHistory, AgentReply, AgentRequest, RunConfig, Task
from .providers.base import Provider


class BudgetExceeded(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class RunContext:
    def __init__(
        self,
        provider: Provider,
        task: Task,
        config: RunConfig,
        cancellation: threading.Event | None = None,
    ) -> None:
        self.provider = provider
        self.task = task
        self.config = config
        self.cancellation = cancellation or threading.Event()
        self.started = time.monotonic()
        self.first_call = len(provider.calls)
        self.history: list[ActionHistory] = []

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def check(self, *, request: bool = False) -> None:
        if self.cancellation.is_set():
            raise Cancelled("Run cancelled before its next operation")
        if self.elapsed >= self.config.max_seconds:
            raise BudgetExceeded("Wall-clock budget exhausted")
        if request and len(self.provider.calls) - self.first_call >= self.config.max_requests:
            raise BudgetExceeded("Model request budget exhausted")

    def decide(self, request: DecisionRequest) -> DecisionReply:
        self.check(request=True)
        if not self.provider.capabilities.decisions:
            raise ValueError("Selected provider does not support typed decisions")
        if request.images and not self.provider.capabilities.vision:
            raise ValueError("Selected provider does not support screenshot decisions")
        return self.provider.decide(request)

    def generate(self, request: AgentRequest) -> AgentReply:
        self.check(request=True)
        if not self.provider.capabilities.generation:
            raise ValueError("Selected provider does not support generative tool calls")
        return self.provider.generate(request)
