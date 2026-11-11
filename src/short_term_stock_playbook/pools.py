"""三层标的池的构建逻辑（纯函数，不碰网络，便于单测与回测复用）。"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from .config import HANDOFF_MIN_AMOUNT, HIST_WINDOW_2, HIST_WINDOW_4, TOP_N

EMPTY_COLS = ["code", "name"]


def pool_a(spot_df: pd.DataFrame, n: int = TOP_N) -> pd.DataFrame:
    """池 A：昨日成交额前 N。

    传入的 spot_df 应为「昨日收盘后」的快照（或昨日日线聚合结果）。
    返回列：code, name, amount, amount_rank（rank 从 1 开始）。
    """
    if spot_df is None or spot_df.empty:
        return pd.DataFrame(columns=[*EMPTY_COLS, "amount", "amount_rank"])
    df = spot_df.sort_values("amount", ascending=False).head(n).copy()
    df["amount_rank"] = range(1, len(df) + 1)
    return df[[*EMPTY_COLS, "amount", "amount_rank"]].reset_index(drop=True)


def strength(pool: pd.DataFrame, today_spot: pd.DataFrame) -> int:
    """S 值：池 A 中今日上涨的只数。

    today_spot 需含 code / pct 两列。停牌（查不到 pct）不计入上涨。
    """
    if pool is None or pool.empty or today_spot is None or today_spot.empty:
        return 0
    merged = pool[["code"]].merge(today_spot[["code", "pct"]], on="code", how="left")
    return int((merged["pct"].fillna(0) > 0).sum())


def pool_b(
    prev_zt: pd.DataFrame,
    today_zt: pd.DataFrame,
    min_amount: float = HANDOFF_MIN_AMOUNT,
) -> pd.DataFrame:
    """池 B：10 亿首板 + 次日连板 → 命中的方向。

    参数
    ----
    prev_zt  : 昨日涨停池（含 boards / amount）
    today_zt : 今日涨停池（含 boards）

    返回列：code, name, amount, boards（仅承接成功的票）。
    TODO: 板块归属需要 stock_individual_info_em 或板块成分接口，
          骨架里先只返回个股，方向聚合留待接入 sector 数据。
    """
    cols = [*EMPTY_COLS, "amount", "boards"]
    if prev_zt is None or prev_zt.empty or today_zt is None or today_zt.empty:
        return pd.DataFrame(columns=cols)

    first_board = prev_zt[(prev_zt["boards"] == 1) & (prev_zt["amount"] >= min_amount)]
    if first_board.empty:
        return pd.DataFrame(columns=cols)

    promoted = today_zt[today_zt["boards"] >= 2][["code", "boards"]]
    hit = first_board.merge(promoted, on="code", how="inner", suffixes=("", "_today"))
    return hit[cols].reset_index(drop=True)


def pool_c(
    hist: pd.DataFrame,
    asof: dt.date,
    window2: int = HIST_WINDOW_2,
    window4: int = HIST_WINDOW_4,
) -> pd.DataFrame:
    """池 C：连板历史票。

    参数
    ----
    hist : 涨停历史，需含 code / name / boards / trade_date（由 data.zt_history 生成）
    asof : 计算基准日（不含当日）

    返回列：code, name, tag(C1/C2), max_boards, last_zt

    C1 = 近 window2 个交易日内出现过二连板
    C2 = 近 window4 个交易日内出现过四连板（优先级更高）
    """
    cols = [*EMPTY_COLS, "tag", "max_boards", "last_zt"]
    if hist is None or hist.empty:
        return pd.DataFrame(columns=cols)

    df = hist.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    cutoff = pd.Timestamp(asof)
    days = sorted(d for d in df["trade_date"].unique() if d <= cutoff)
    if not days:
        return pd.DataFrame(columns=cols)

    def _collect(window: int, min_boards: int, tag: str) -> pd.DataFrame:
        window_days = {pd.Timestamp(d) for d in days[-window:]}
        sub = df[df["trade_date"].isin(window_days) & (df["boards"] >= min_boards)]
        if sub.empty:
            return pd.DataFrame(columns=cols)
        agg = (
            sub.groupby(["code", "name"])
            .agg(max_boards=("boards", "max"), last_zt=("trade_date", "max"))
            .reset_index()
        )
        agg["tag"] = tag
        return agg[cols]

    c1 = _collect(window2, 2, "C1")
    c2 = _collect(window4, 4, "C2")
    out = pd.concat([c2, c1], ignore_index=True)
    if out.empty:
        return pd.DataFrame(columns=cols)
    # 同一只票既有 C2 又有 C1 时保留 C2（历史连板更高，优先级更高）
    out["_priority"] = out["tag"].map({"C2": 0, "C1": 1}).fillna(2)
    out = out.sort_values(["code", "_priority"]).drop_duplicates(subset=["code"], keep="first")
    return out.drop(columns="_priority").reset_index(drop=True)


def position_cap(s_value: int) -> float:
    """池 A 给出的单票仓位上限。"""
    from .config import S_POSITION

    return S_POSITION.get(int(s_value), 0.0)


def all_pools_empty(
    a: Optional[pd.DataFrame], b: Optional[pd.DataFrame], c: Optional[pd.DataFrame]
) -> bool:
    """三层池只要有空 → 当天不做。"""
    for frame in (a, b, c):
        if frame is None or frame.empty:
            return True
    return False
