"""Append-only trade journal so every decision can be reviewed and scored later."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, state_dir: Path, run_id: str, mode: str) -> None:
        self.path = state_dir / "journal.jsonl"
        self.run_id = run_id
        self.mode = mode

    def log(self, kind: str, **data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "run": self.run_id,
            "mode": self.mode,
            "kind": kind,
            **data,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
