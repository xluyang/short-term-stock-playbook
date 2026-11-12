"""同花顺自选股分组同步。

把三层池导出成「分组名 → 股票代码列表」，默认 dry-run 只生成
``output/ths_manifest.json`` 并打印摘要；``--apply`` 时默认调用内置的
``ths_store.store_adapter``，把三组覆盖写进本机同花顺自选股分组。

要接外部工具（如 ths-favorite）替代内置写入，传 ``adapter`` 可调用对象即可，
入参是 manifest dict。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from .config import output_dir

# 分组名固定，靠「覆盖内容」而不是「每天建新组」；空池给空列表（对应删空组）。
GROUP_NAMES = ("TOP5", "池B承接", "池C连板")


def market_prefix(code: str) -> str:
    """6 位代码 → 交易所前缀（同花顺分组需要区分市场）。

    6xxxxx → SH（沪主板/科创）；0xxxxx/3xxxxx → SZ（深主板/创业）；
    4xxxxx/8xxxxx → BJ（北交所）。未知市场显式返回 "??"，不静默猜错。
    """
    code = str(code).strip().zfill(6)
    if code[0] == "6":
        return "SH"
    if code[0] in ("0", "3"):
        return "SZ"
    if code[0] in ("4", "8"):
        return "BJ"
    return "??"


def _prefixed(code: str) -> str:
    return f"{market_prefix(code)}{str(code).strip().zfill(6)}"


def build_manifest(a: pd.DataFrame, b: pd.DataFrame, c: pd.DataFrame) -> Dict[str, List[str]]:
    """三层池 → {分组名: [带市场前缀的代码]}。空池 → 空列表。"""
    result: Dict[str, List[str]] = {}
    for name, frame in zip(GROUP_NAMES, (a, b, c)):
        if frame is None or frame.empty or "code" not in frame.columns:
            result[name] = []
            continue
        result[name] = [_prefixed(x) for x in frame["code"].tolist()]
    return result


def write_manifest(manifest: Dict[str, List[str]], path: Optional[Path] = None) -> Path:
    """把 manifest 落成 JSON；不指定路径则写到 output/ths_manifest.json。"""
    path = path or output_dir() / "ths_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


Adapter = Callable[[Dict[str, List[str]]], None]


def _print_summary(manifest: Dict[str, List[str]], path: Path, dry_run: bool) -> None:
    tag = "（dry-run，未真正写入）" if dry_run else ""
    print(f"\n同花顺分组同步{tag}")
    for name, codes in manifest.items():
        preview = ", ".join(codes[:6]) + (", …" if len(codes) > 6 else "")
        print(f"  {name:<6} {len(codes):>2} 只   {preview}")
    print(f"\n清单已写入：{path}")


def sync_ths(
    trade_date: Optional[dt.date] = None,
    offline: bool = False,
    source: str = "auto",
    history_days: int = 90,
    adapter: Optional[Adapter] = None,
    dry_run: bool = True,
) -> int:
    """计算三层池 → 生成 manifest → 可选地调用 adapter 写同花顺。

    返回 0 成功 / 3 取数失败 / 4 未找到同花顺或写入失败（与其它子命令错开）。
    """
    from . import (  # 延迟导入，避免顶层拖入 akshare / 文件定位逻辑
        config,
        data,
        pools,
        ths_store,
    )

    day = trade_date or dt.date.today()
    try:
        spot_df = data.spot(day, offline=offline, source=source)
        pool_a = pools.pool_a(spot_df, config.TOP_N)
        today_zt = data.zt_pool(day, offline=offline)
        prev_zt = data.prev_zt_pool(day, offline=offline)
        pool_b = pools.pool_b(prev_zt, today_zt, config.HANDOFF_MIN_AMOUNT)
        days = data.trade_dates(day, history_days, offline=offline)
        hist = data.zt_history(days, offline=offline)
        pool_c = pools.pool_c(hist, day)
    except data.DataError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    manifest = build_manifest(pool_a, pool_b, pool_c)
    path = write_manifest(manifest)
    _print_summary(manifest, path, dry_run)

    if not dry_run:
        if adapter is None:
            adapter = ths_store.store_adapter
        try:
            adapter(manifest)
        except ths_store.ThsStoreError as exc:
            print(str(exc), file=sys.stderr)
            return 4

    return 0
