"""In-memory one-to-many template index with conservative decision rules."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from app.core.config import settings


@dataclass(slots=True)
class MatchResult:
    decision: str  # identified | unknown | ambiguous | empty
    employee_id: str | None
    score: float
    second_employee_id: str | None
    second_score: float


class TemplateIndex:
    """Holds decrypted, L2-normalised templates in RAM only. Rebuilt from the DB on demand."""

    def __init__(self, dim: int | None = None) -> None:
        self._lock = threading.RLock()
        self.dim = dim  # None: taken from the first load
        self._matrix = np.zeros((0, dim or 0), np.float32)
        self._owners: list[str] = []
        self.version = 0

    def load(self, rows: list[tuple[str, np.ndarray]]) -> None:
        with self._lock:
            if self.dim is None and rows:
                self.dim = len(rows[0][1])
            # Templates from another embedding model (different length) can never be compared — leave them out.
            rows = [(e, v) for e, v in rows if len(v) == self.dim]
            if rows:
                self._matrix = np.stack([v for _, v in rows]).astype(np.float32)
                self._owners = [e for e, _ in rows]
            else:
                self._matrix = np.zeros((0, self.dim or 0), np.float32)
                self._owners = []
            self.version += 1

    @property
    def size(self) -> int:
        return len(self._owners)

    def employees(self) -> set[str]:
        with self._lock:
            return set(self._owners)

    def best_per_employee(self, probe: np.ndarray) -> list[tuple[str, float]]:
        with self._lock:
            if not self._owners:
                return []
            sims = self._matrix @ probe.astype(np.float32)
            best: dict[str, float] = {}
            for owner, s in zip(self._owners, sims):
                if s > best.get(owner, -2.0):
                    best[owner] = float(s)
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)

    def match(self, probe: np.ndarray, *, accept: float | None = None, margin: float | None = None) -> MatchResult:
        accept = settings.match_accept_threshold if accept is None else accept
        margin = settings.match_margin if margin is None else margin
        ranked = self.best_per_employee(probe)
        if not ranked:
            return MatchResult("empty", None, 0.0, None, 0.0)
        top_id, top = ranked[0]
        sec_id, sec = (ranked[1] if len(ranked) > 1 else (None, 0.0))
        if top < accept:
            return MatchResult("unknown", None, top, sec_id, sec)
        if sec_id is not None and (top - sec) < margin and sec >= accept * 0.85:
            return MatchResult("ambiguous", None, top, sec_id, sec)
        return MatchResult("identified", top_id, top, sec_id, sec)

    def find_duplicates(self, probe: np.ndarray, threshold: float | None = None) -> list[tuple[str, float]]:
        threshold = settings.duplicate_enrol_threshold if threshold is None else threshold
        return [(e, s) for e, s in self.best_per_employee(probe) if s >= threshold]
