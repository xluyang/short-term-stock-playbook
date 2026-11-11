"""打分卡（纯函数，零依赖，方便单测与回测扫描）。

总分 = 环境 30 + 方向 25 + 资质 20 + 时间窗 15 + 形态 10，≥70 才下单。
"""

from __future__ import annotations

from typing import Dict, Optional

from .config import (
    EXEC_END,
    EXEC_START,
    MIN_SCORE,
    POSITION_BANDS,
    WEIGHTS,
)

FORM_SCORES = {"pullback": 10, "flat": 6, "straight": 0}


def env_points(s_value: int) -> int:
    """环境分：S=5→30，4→24，3→15，≤2→0。"""
    return {5: 30, 4: 24, 3: 15}.get(int(s_value), 0)


def sector_points(sector_hit: bool, in_sector: bool) -> int:
    """方向分：池 B 命中且个股属该方向→25；仅方向命中→15；否则 0。"""
    if not sector_hit:
        return 0
    return 25 if in_sector else 15


def quality_points(amount_rank: Optional[int]) -> int:
    """资质分：昨日成交额排名前 20→20，前 50→12，其余→5，未知→5。"""
    if amount_rank is None:
        return 5
    if amount_rank <= 20:
        return 20
    if amount_rank <= 50:
        return 12
    return 5


def timing_points(minutes_from_open: Optional[float]) -> int:
    """时间窗分：9:50–10:10 首次触板→15；10:10–10:30→10；窗口外→0。

    minutes_from_open 以 9:30 为 0 点（9:50 → 20，10:30 → 60）。
    """
    if minutes_from_open is None:
        return 0
    m = float(minutes_from_open)
    if EXEC_START <= m <= EXEC_START + 20:
        return 15
    if EXEC_START + 20 < m <= EXEC_END:
        return 10
    return 0


def form_points(form: str) -> int:
    """形态分：回踩后拉起→10；平开震荡后上攻→6；直线拉→0。"""
    return FORM_SCORES.get(str(form or "").lower(), 0)


def score(
    s_value: int,
    sector_hit: bool = False,
    in_sector: bool = False,
    amount_rank: Optional[int] = None,
    minutes_from_open: Optional[float] = None,
    form: str = "flat",
) -> Dict[str, object]:
    """计算总分，返回各维度明细，便于日志与复盘。"""
    parts = {
        "env": env_points(s_value),
        "sector": sector_points(sector_hit, in_sector),
        "quality": quality_points(amount_rank),
        "timing": timing_points(minutes_from_open),
        "form": form_points(form),
    }
    total = sum(parts.values())
    return {"parts": parts, "weights": dict(WEIGHTS), "total": total, "pass": total >= MIN_SCORE}


def position_for(total: float, cap: float) -> float:
    """最终仓位 = min(打分对应档位, 池 A 给出的上限)。"""
    band = 0.0
    for threshold, ratio in POSITION_BANDS:
        if total >= threshold:
            band = ratio
            break
    return round(min(band, max(cap, 0.0)), 4)
