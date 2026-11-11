"""模型参数与路径。

所有阈值集中在这里：回测调参只改本文件，不改逻辑。
参数含义见 docs/model.md。
"""

from __future__ import annotations

import os
from pathlib import Path

# ---- 池 A：环境开关 -----------------------------------------------------
TOP_N = 5                      # 昨日成交额取前 N
MIN_S = 3                      # S 低于此值空仓
S_POSITION = {5: 0.30, 4: 0.22, 3: 0.12}   # S -> 单票仓位上限

# ---- 池 B：方向承接 -----------------------------------------------------
HANDOFF_MIN_AMOUNT = 10e8      # 首板日成交额下限（10 亿）

# ---- 池 C：人气股 -------------------------------------------------------
HIST_WINDOW_2 = 10             # 近 N 个交易日出现过二连板
HIST_WINDOW_4 = 90             # 近 N 个交易日出现过四连板

# ---- 硬性过滤 -----------------------------------------------------------
MIN_AMOUNT = 5e8               # 当日成交额下限（5 亿）
MAX_OPEN_5MIN_PCT = 5.0        # 开盘 5 分钟涨幅上限（%）
SEAL_RATIO_MIN = 0.003         # 封单 / 流通市值 下限（3‰）
MAX_MARKET_DROP_PCT = -1.5     # 指数跌幅超过此值全局停手
MAX_BROKEN_RATE = 0.40         # 全市场炸板率超过此值停手
MIN_SECTOR_ZT = 2              # 板块涨停家数下限

# ---- 时间窗（分钟，从 9:30 起算）---------------------------------------
OBSERVE_START = 0              # 9:30
EXEC_START = 20                # 9:50
EXEC_END = 60                  # 10:30

# ---- 打分卡 -------------------------------------------------------------
WEIGHTS = {"env": 30, "sector": 25, "quality": 20, "timing": 15, "form": 10}
MIN_SCORE = 70                 # 低于此分不下单
POSITION_BANDS = ((90, 0.30), (80, 0.20), (70, 0.10))


def home() -> Path:
    """项目根目录，可用 LIMITUP_HOME 覆盖。"""
    raw = os.environ.get("LIMITUP_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def cache_dir() -> Path:
    """行情缓存目录，可用 LIMITUP_CACHE_DIR 覆盖。"""
    raw = os.environ.get("LIMITUP_CACHE_DIR")
    base = Path(raw).expanduser().resolve() if raw else home() / "cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def output_dir() -> Path:
    raw = os.environ.get("LIMITUP_OUTPUT_DIR")
    base = Path(raw).expanduser().resolve() if raw else home() / "output"
    base.mkdir(parents=True, exist_ok=True)
    return base
