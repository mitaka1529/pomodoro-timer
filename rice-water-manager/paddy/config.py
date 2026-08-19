"""設定ファイルの読み込みと生育ステージの解決。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class StageOverride:
    name: str
    start: str  # "MM-DD"
    end: str    # "MM-DD"（両端を含む。年またぎ可）
    target_level_mm: float
    valve_locked_closed: bool = False

    def contains(self, day: dt.date) -> bool:
        key = day.strftime("%m-%d")
        if self.start <= self.end:
            return self.start <= key <= self.end
        # 年またぎ（例 11-01 〜 02-28）
        return key >= self.start or key <= self.end


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path
    stage_overrides: list[StageOverride] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        stages = [StageOverride(**s) for s in raw.get("stage_overrides") or []]
        return cls(raw=raw, path=path, stage_overrides=stages)

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name) or {})

    def resolve_path(self, value: str) -> Path:
        """設定ファイルからの相対パスを絶対パスに変換する。"""
        p = Path(value)
        return p if p.is_absolute() else self.path.parent / p

    def active_stage(self, day: dt.date | None = None) -> StageOverride | None:
        day = day or dt.date.today()
        for stage in self.stage_overrides:
            if stage.contains(day):
                return stage
        return None

    def target_level_mm(self, day: dt.date | None = None) -> float:
        stage = self.active_stage(day)
        if stage is not None:
            return float(stage.target_level_mm)
        return float(self.section("control").get("target_level_mm", 50))
