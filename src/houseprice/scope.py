"""Scope layer: extract structured scope from free-text job_description.

The brief: no sqft/fixture/complexity fields exist — they must come from the description.
Three interchangeable backends (user directive: claude_cli now, swap to api key later):
  - deterministic : regex/keyword, ALWAYS available (deploy floor, no deps, <1ms)
  - claude_cli    : shells to `claude -p` (offline / local enrichment)
  - anthropic_api : Anthropic SDK via ANTHROPIC_API_KEY (drop-in for deployment)
All backends emit the SAME schema so the model and sidecar never branch on backend:
  {scope_sqft: float|-1, scope_fixture_count: float|-1, scope_complexity: 0|1|2, scope_urgency: 0..3}
"""
from __future__ import annotations

import json
import os
import re
import subprocess

SCHEMA_KEYS = ["scope_sqft", "scope_fixture_count", "scope_complexity", "scope_urgency"]

_SQFT = re.compile(r"(\d[\d,]*)\s*(?:sq\.?\s?ft|square\s?f(?:ee|oo)t|sf)\b", re.I)
_ROOMS = re.compile(r"(\d+)\s*(?:br|bed|bedroom|bath|room|story|stories|window|unit|fixture|outlet|valve)", re.I)
_COMPLEX_HI = re.compile(r"\b(whole|entire|full|complete|remodel|replace|install|multiple|several|major|2-?story|two-?story)\b", re.I)
_COMPLEX_LO = re.compile(r"\b(small|minor|single|one|simple|quick|patch|touch ?up|you supply|i have)\b", re.I)
_URGENT = re.compile(r"\b(emergency|asap|urgent|today|tonight|right now|immediately)\b", re.I)


def deterministic_scope(desc: str, category: str = "") -> dict:
    d = desc or ""
    sqft = -1.0
    m = _SQFT.search(d)
    if m:
        try:
            sqft = float(m.group(1).replace(",", ""))
        except ValueError:
            sqft = -1.0
    counts = [int(x) for x in _ROOMS.findall(d)]
    fixtures = float(max(counts)) if counts else -1.0
    hi = len(_COMPLEX_HI.findall(d))
    lo = len(_COMPLEX_LO.findall(d))
    complexity = 2 if hi > lo and hi >= 2 else (1 if hi >= 1 and hi >= lo else 0)
    urgency = 3 if _URGENT.search(d) else 1
    return {"scope_sqft": sqft, "scope_fixture_count": fixtures,
            "scope_complexity": complexity, "scope_urgency": urgency}


_BATCH_PROMPT = (
    "You extract structured scope from home-service job descriptions. For EACH numbered item "
    "return a JSON object. Output ONLY a JSON array, one object per item, no prose.\n"
    "Each object: {\"idx\": <int>, \"sqft\": <number or null>, \"fixture_count\": <int or null>, "
    "\"complexity\": \"low\"|\"medium\"|\"high\", \"urgency\": 0|1|2|3}\n"
    "sqft = explicit area if stated else null. fixture_count = count of discrete units "
    "(rooms, windows, outlets, valves, fixtures) if inferable else null. complexity = job scale. "
    "urgency: 0 flexible, 1 normal, 2 soon, 3 emergency.\n\nItems:\n"
)
_COMPLEX_MAP = {"low": 0, "medium": 1, "med": 1, "high": 2}


def _coerce(obj: dict) -> dict:
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return -1.0
    return {
        "scope_sqft": num(obj.get("sqft")) if obj.get("sqft") is not None else -1.0,
        "scope_fixture_count": num(obj.get("fixture_count")) if obj.get("fixture_count") is not None else -1.0,
        "scope_complexity": _COMPLEX_MAP.get(str(obj.get("complexity", "")).lower(), 1),
        "scope_urgency": int(obj.get("urgency", 1)) if str(obj.get("urgency", "")).strip().isdigit() else 1,
    }


class ScopeExtractor:
    def __init__(self, backend: str | None = None, model: str = "claude-haiku-4-5-20251001"):
        self.backend = backend or os.environ.get("SCOPE_BACKEND", "deterministic")
        self.model = model

    def extract(self, desc: str, category: str = "") -> dict:
        if self.backend == "anthropic_api" and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                return self._anthropic([desc])[0]
            except Exception:
                pass
        if self.backend == "claude_cli":
            try:
                return self.extract_batch([desc])[0]
            except Exception:
                pass
        return deterministic_scope(desc, category)

    def extract_batch(self, descs: list[str]) -> list[dict]:
        """claude_cli batch. Falls back to deterministic per-item on any parse failure."""
        if self.backend != "claude_cli":
            return [deterministic_scope(d) for d in descs]
        items = "\n".join(f"{i}. {d[:500]}" for i, d in enumerate(descs))
        prompt = _BATCH_PROMPT + items
        try:
            out = subprocess.run(
                ["claude", "-p", prompt], capture_output=True, text=True, timeout=120,
                cwd="/tmp",  # neutral cwd: don't load this project's CLAUDE.md into the prompt
            ).stdout
            arr = json.loads(re.search(r"\[.*\]", out, re.S).group(0))
            by_idx = {int(o["idx"]): _coerce(o) for o in arr if "idx" in o}
            return [by_idx.get(i, deterministic_scope(descs[i])) for i in range(len(descs))]
        except Exception:
            return [deterministic_scope(d) for d in descs]

    def _anthropic(self, descs: list[str]) -> list[dict]:
        import anthropic  # lazy
        client = anthropic.Anthropic()
        items = "\n".join(f"{i}. {d[:500]}" for i, d in enumerate(descs))
        msg = client.messages.create(
            model=self.model, max_tokens=1024,
            messages=[{"role": "user", "content": _BATCH_PROMPT + items}],
        )
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        arr = json.loads(re.search(r"\[.*\]", txt, re.S).group(0))
        by_idx = {int(o["idx"]): _coerce(o) for o in arr if "idx" in o}
        return [by_idx.get(i, deterministic_scope(descs[i])) for i in range(len(descs))]
