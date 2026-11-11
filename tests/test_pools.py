"""标的池构建单测：用构造数据，不联网。"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from short_term_stock_playbook import pools


def _spot():
    return pd.DataFrame(
        {
            "code": [f"{i:06d}" for i in range(1, 7)],
            "name": [f"票{i}" for i in range(1, 7)],
            "amount": [1e9, 5e9, 3e9, 2e9, 4e9, 8e8],
            "pct": [1.0, 2.0, -1.0, 0.5, 3.0, -2.0],
        }
    )


def test_pool_a_takes_top_n_and_ranks():
    pool = pools.pool_a(_spot(), n=3)
    assert list(pool["code"]) == ["000002", "000005", "000003"]
    assert list(pool["amount_rank"]) == [1, 2, 3]
    assert len(pool) == 3


def test_pool_a_empty_input():
    assert pools.pool_a(pd.DataFrame(columns=["code", "amount"])).empty


def test_strength_counts_rising():
    pool = pd.DataFrame({"code": ["000001", "000002"]})
    today = pd.DataFrame({"code": ["000001", "000002", "000003"], "pct": [2.0, -1.0, 5.0]})
    assert pools.strength(pool, today) == 1


def test_strength_ignores_suspended():
    pool = pd.DataFrame({"code": ["000001", "000009"]})
    today = pd.DataFrame({"code": ["000001"], "pct": [1.0]})
    assert pools.strength(pool, today) == 1


def test_pool_b_requires_big_first_board_and_promotion():
    prev = pd.DataFrame(
        {
            "code": ["000001", "000002", "000003"],
            "name": ["大票", "小票", "断板"],
            "amount": [12e8, 5e8, 20e8],
            "boards": [1, 1, 1],
        }
    )
    today = pd.DataFrame({"code": ["000001", "000003"], "boards": [2, 1]})
    hit = pools.pool_b(prev, today, min_amount=10e8)
    assert list(hit["code"]) == ["000001"]


def test_pool_b_empty_when_no_promotion():
    prev = pd.DataFrame({"code": ["000001"], "name": ["x"], "amount": [12e8], "boards": [1]})
    today = pd.DataFrame({"code": ["000001"], "boards": [1]})
    assert pools.pool_b(prev, today).empty


def test_pool_c_windows_and_priority():
    hist = pd.DataFrame(
        {
            "code": ["A", "B", "C", "D", "D"],
            "name": ["票A", "票B", "票C", "票D", "票D"],
            "boards": [2, 4, 3, 2, 4],
            "trade_date": pd.to_datetime(
                ["2026-11-05", "2026-11-03", "2026-11-02", "2026-11-05", "2026-11-04"]
            ),
        }
    )
    asof = dt.date(2026, 11, 6)
    result = pools.pool_c(hist, asof, window2=2, window4=5)

    tags = dict(zip(result["code"], result["tag"]))
    assert tags["A"] == "C1", "近 2 日内二连板 -> C1"
    assert tags["B"] == "C2", "近 5 日内四连板 -> C2"
    assert "C" not in tags, "3 连板但不在近 2 日窗口内 -> 不入池"
    assert tags["D"] == "C2", "同时满足 C1/C2 时保留 C2"


def test_pool_c_empty_history():
    assert pools.pool_c(pd.DataFrame(), dt.date(2026, 11, 6)).empty


def test_position_cap():
    assert pools.position_cap(5) == 0.30
    assert pools.position_cap(4) == 0.22
    assert pools.position_cap(3) == 0.12
    assert pools.position_cap(2) == 0.0


def test_all_pools_empty():
    frame = pd.DataFrame({"code": ["1"]})
    assert pools.all_pools_empty(frame, frame, pd.DataFrame()) is True
    assert pools.all_pools_empty(frame, frame, frame) is False
