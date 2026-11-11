"""数据层：akshare 取数 + 列名归一化 + 本地缓存。

设计要点
--------
1. **只有本文件碰 akshare**。上游列名一变，只改这里的映射表。
2. 归一化后所有函数返回固定的英文列，逻辑层永远不用管中文列名。
3. 每个请求都落一份 csv 缓存（按日期分文件），方便回放与排查。

NOTE: akshare 的接口签名在不同版本间会变。若报错，先跑 `short-term-stock-playbook doctor`
看当前 akshare 版本，再对照官方文档调整 `_ak(...)` 的调用参数。
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, List, Optional

import pandas as pd

from .config import cache_dir


class DataError(RuntimeError):
    """取数失败（依赖缺失 / 接口变更 / 网络问题）。"""


_RATE_HINT = (
    "\n\n东方财富对高频请求做了 IP 限流。处理顺序：\n"
    "  1) 已有当日缓存 → 加 `--offline` 直接读缓存，完全不发请求；\n"
    "     short-term-stock-playbook pools --offline\n"
    "  2) 没有缓存 → 等 5 分钟以上再试。**期间不要反复重试**，会延长限流时间；\n"
    "  3) 收盘后 15:05 起 spot 会自动复用当日缓存，一天只需要拉一次。"
)

_RATE_KEYS = ("限流", "断开", "远程", "Max retries", "Connection", "Timeout", "timed out")


def _explain(exc: Exception) -> str:
    """把限流类错误翻译成可操作的步骤，其它错误原样返回。"""
    text = str(exc)
    if any(k in text for k in _RATE_KEYS):
        return f"{text}{_RATE_HINT}"
    return text


def _after_close() -> bool:
    """收盘数据是否已终值（留 5 分钟给交易所结算）。"""
    now = dt.datetime.now()
    return now.time() >= dt.time(15, 5)


def _ak():
    try:
        import akshare as ak  # noqa: PLC0415 - 延迟导入，避免没装时整个包不可用
    except ImportError as exc:  # pragma: no cover
        raise DataError("需要 akshare：pip install -e .  （或 pip install akshare）") from exc
    return ak


def ak_version() -> str:
    try:
        import akshare as ak

        return getattr(ak, "__version__", "unknown")
    except Exception:
        return "not installed"


# ------------------------------------------------------------------ 列名映射
SPOT_MAP = {
    "代码": "code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "pct",
    "成交额": "amount",
    "换手率": "turnover",
    "流通市值": "float_mv",
    "总市值": "total_mv",
}

# 今日涨停池 stock_zt_pool_em：字段最全（含封单额、首/末封时间、炸板次数）
ZT_MAP = {
    "代码": "code",
    "名称": "name",
    "涨跌幅": "pct",
    "最新价": "price",
    "成交额": "amount",
    "流通市值": "float_mv",
    "总市值": "total_mv",
    "换手率": "turnover",
    "封板资金": "seal_amount",
    "首次封板时间": "first_seal",
    "最后封板时间": "last_seal",
    "炸板次数": "broken_times",
    "连板数": "boards",
    "涨停统计": "stat",
    "所属行业": "sector",
}

# 昨日涨停池 stock_zt_pool_previous_em：**另一套 schema**
# 没有封板资金 / 首次封板时间 / 炸板次数，连板数列名带「昨日」前缀，
# 且多出 涨停价 / 涨速 / 振幅。两套表不能共用同一张映射。
PREV_ZT_MAP = {
    "代码": "code",
    "名称": "name",
    "涨跌幅": "pct",
    "最新价": "price",
    "成交额": "amount",
    "流通市值": "float_mv",
    "总市值": "total_mv",
    "换手率": "turnover",
    "昨日封板时间": "last_seal",
    "昨日连板数": "boards",
    "涨停统计": "stat",
    "所属行业": "sector",
}


def _normalize(
    df: pd.DataFrame,
    mapping: dict,
    table: str,
    required: tuple = (),
) -> pd.DataFrame:
    """按映射重命名并裁剪列。

    `required` 是**逻辑真正依赖**的目标列名（如 code / boards / amount）。
    它们缺失时直接报错 —— 宁可崩，也不要静默算出全 False 的结论。
    其余映射列为「有就带上，没有就补 NA」，这样 akshare 增删锦上添花的字段
    不会让整个命令挂掉。
    """
    if df is None or df.empty:
        cols = list(mapping.values())
        cols.extend(c for c in required if c not in cols)
        return pd.DataFrame(columns=cols)

    renamed = {c: mapping[c] for c in df.columns if c in mapping}
    out = df.rename(columns=renamed).copy()

    missing = [c for c in required if c not in out.columns]
    if missing:
        raise DataError(
            f"{table} 缺少必需列 {missing}；实际列为 {list(df.columns)}。\n"
            f"多半是 akshare 版本变更，请更新 data.py 中的 {table} 映射表。"
        )

    for dst in mapping.values():
        if dst not in out.columns:
            out[dst] = pd.NA
    return out[list(mapping.values())]


def _cache(df: pd.DataFrame, name: str, date: dt.date) -> None:
    path = cache_dir() / f"{name}_{date:%Y%m%d}.csv"
    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    except Exception:
        pass  # 缓存失败不影响主流程


def _cached_read(name: str, date: dt.date) -> Optional[pd.DataFrame]:
    """读本地 csv 缓存，不存在或损坏时返回 None。

    注意：股票代码是 6 位带前导零的字符串（000525 / 002889）。
    CSV 往返后 pandas 会把它推断成整数，`000525` 变成 `525`，
    进而让池 B 的 merge 与池 C 的展示全部错位 —— 必须显式按字符串读。
    """
    path = cache_dir() / f"{name}_{date:%Y%m%d}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype={"code": str})
    except Exception:
        return None
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def _try_cache(name: str, day: dt.date, offline: bool) -> Optional[pd.DataFrame]:
    """决定这一天能不能读缓存。

    - 历史交易日：一定可读（数据已定型）
    - 当日 + 已收盘（15:05 之后）：可读（当日数据已终值）
    - 当日 + 盘中：不读（会拿到过期数据），除非用户显式 --offline
    """
    today = dt.date.today()
    if day < today or offline or (day == today and _after_close()):
        return _cached_read(name, day)
    return None


def to_date_str(value) -> str:
    """统一成 akshare 需要的 YYYYMMDD。"""
    if isinstance(value, dt.date):
        return value.strftime("%Y%m%d")
    text = str(value).replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        raise DataError(f"日期格式应为 YYYYMMDD 或 YYYY-MM-DD，收到 {value!r}")
    return text


# ------------------------------------------------------------------ 行情快照
def spot(trade_date: Optional[dt.date] = None, offline: bool = False) -> pd.DataFrame:
    """全市场实时/收盘行情快照。

    `stock_zh_a_spot_em` 一次要翻几十页拉全市场 5000+ 只票，是东财限流的头号
    触发点。所以：

    - **15:05 之后**：当日数据已终值，若当日缓存存在就直接复用，不再打接口；
    - **盘中**：每次都取实时值（缓存会过时），因此盘中别高频重跑；
    - `offline=True`：完全不联网，只读缓存，没有就报错。

    时点提示：开盘前调用拿到的是**昨日收盘**数据（模型要的就是这个，无未来函数）；
    收盘后调用拿到的是**今日**数据（用于复盘与准备明天的池）。
    """
    day = trade_date or dt.date.today()
    cached = _cached_read("spot", day)

    if cached is not None and (offline or _after_close()):
        if {"code", "amount", "pct"} <= set(cached.columns):
            return cached

    if offline:
        raise DataError(
            f"离线模式：找不到 {day:%Y-%m-%d} 的行情缓存（cache/spot_{day:%Y%m%d}.csv）。\n"
            f"先联网跑一次 `short-term-stock-playbook pools` 生成缓存，之后就能用 --offline 复用。"
        )

    ak = _ak()
    try:
        raw = ak.stock_zh_a_spot_em()
    except Exception as exc:
        raise DataError(f"拉取行情快照失败：{_explain(exc)}") from exc
    df = _normalize(
        raw, SPOT_MAP, "stock_zh_a_spot_em", required=("code", "name", "amount", "pct")
    )
    _cache(df, "spot", day)
    return df


# ------------------------------------------------------------------ 涨停池
def zt_pool(trade_date, offline: bool = False) -> pd.DataFrame:
    """指定交易日的涨停股池（含连板数、封单额、封板时间）。

    历史日期优先读 `cache/zt_pool_YYYYMMDD.csv`：池 C 需要回看 90 个交易日，
    没有缓存每次要重拉 90 次请求。当日是否可读缓存由 `_try_cache` 决定。
    """
    date_str = to_date_str(trade_date)
    day = dt.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))

    cached = _try_cache("zt_pool", day, offline)
    if cached is not None and {"code", "boards"} <= set(cached.columns):
        cached["boards"] = pd.to_numeric(cached["boards"], errors="coerce")
        if "trade_date" in cached.columns:
            cached["trade_date"] = pd.to_datetime(cached["trade_date"])
        return cached

    if offline:
        raise DataError(
            f"离线模式：缺少 {day:%Y-%m-%d} 的涨停池缓存（cache/zt_pool_{day:%Y%m%d}.csv）。"
        )

    ak = _ak()
    try:
        raw = ak.stock_zt_pool_em(date=date_str)
    except Exception as exc:
        raise DataError(f"拉取 {date_str} 涨停池失败：{_explain(exc)}") from exc
    df = _normalize(
        raw, ZT_MAP, "stock_zt_pool_em", required=("code", "name", "boards", "amount")
    )
    df["trade_date"] = pd.to_datetime(date_str)
    _cache(df, "zt_pool", day)
    return df


def prev_zt_pool(trade_date, offline: bool = False) -> pd.DataFrame:
    """昨日涨停池（用于判断「次日是否连板」的承接）。

    注意：akshare 这里返回的是**另一套列**（昨日连板数 / 昨日封板时间，
    且没有封板资金与炸板次数），所以走 `PREV_ZT_MAP` 而不是 `ZT_MAP`。
    """
    date_str = to_date_str(trade_date)
    day = dt.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))

    cached = _try_cache("prev_zt", day, offline)
    if cached is not None and {"code", "boards"} <= set(cached.columns):
        cached["boards"] = pd.to_numeric(cached["boards"], errors="coerce")
        return cached

    if offline:
        raise DataError(
            f"离线模式：缺少 {day:%Y-%m-%d} 的昨日涨停池缓存"
            f"（cache/prev_zt_{day:%Y%m%d}.csv）。"
        )

    ak = _ak()
    try:
        raw = ak.stock_zt_pool_previous_em(date=date_str)
    except Exception as exc:
        raise DataError(f"拉取 {date_str} 昨日涨停池失败：{_explain(exc)}") from exc
    df = _normalize(
        raw,
        PREV_ZT_MAP,
        "stock_zt_pool_previous_em",
        required=("code", "name", "boards", "amount"),
    )
    _cache(df, "prev_zt", day)
    return df


def trade_dates(end: dt.date, count: int, offline: bool = False) -> List[dt.date]:
    """取 end 之前（含）的 count 个交易日。

    交易日历是一份从 1990 年到今天的完整列表，单独缓存成 `cache/trade_cal.csv`，
    24 小时内复用（跨天后重新拉，避免漏掉新交易日）。
    """
    path = cache_dir() / "trade_cal.csv"
    cal = None

    fresh = False
    if path.exists():
        age = dt.datetime.now() - dt.datetime.fromtimestamp(path.stat().st_mtime)
        fresh = age.total_seconds() < 24 * 3600
    if fresh or offline:
        try:
            cal = pd.read_csv(path)
        except Exception:
            cal = None

    if cal is None:
        if offline:
            raise DataError("离线模式：缺少交易日历缓存 cache/trade_cal.csv，先联网跑一次。")
        ak = _ak()
        try:
            cal = ak.tool_trade_date_hist_sina()
        except Exception as exc:
            raise DataError(f"拉取交易日历失败：{_explain(exc)}") from exc
        try:
            cal.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception:
            pass

    col = "trade_date" if "trade_date" in cal.columns else cal.columns[0]
    days = pd.to_datetime(cal[col])
    days = [d.date() for d in days if d.date() <= end]
    return days[-count:]


def zt_history(dates: Iterable[dt.date], offline: bool = False) -> pd.DataFrame:
    """合并多日涨停池，用于构建池 C 的连板历史。

    注意：逐日请求较慢（90 天约 90 次），骨架里先串行 + 缓存，
    后续可换并发或直接用本地数据库。
    """
    frames = []
    for day in dates:
        try:
            frames.append(zt_pool(day, offline=offline))
        except DataError:
            continue  # 停牌日 / 无缓存 / 接口抖动跳过
    if not frames:
        return pd.DataFrame(columns=["code", "name", "boards", "trade_date"])
    return pd.concat(frames, ignore_index=True)
