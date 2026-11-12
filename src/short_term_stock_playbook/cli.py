"""命令行入口。

    short-term-stock-playbook doctor        环境与参数自检
    short-term-stock-playbook pools         构建三层标的池
    short-term-stock-playbook journal       生成交易打卡表（xlsx）
    short-term-stock-playbook screen        当天候选打分（骨架，需人工确认分时）
    short-term-stock-playbook ths           同步三层池到同花顺自选股分组
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Optional, Sequence

from . import __version__, config, report


def _out(msg: str = "") -> None:
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    from . import data

    _out(f"short-term-stock-playbook {__version__}")
    _out("=" * 60)
    _out(f"python         {sys.version.split()[0]}")
    try:
        import pandas as pd

        _out(f"pandas         {pd.__version__}")
    except Exception:
        _out("pandas         未安装")
    _out(f"akshare        {data.ak_version()}")
    _out(f"cache dir      {config.cache_dir()}")
    _out(f"output dir     {config.output_dir()}")
    _out("=" * 60)
    _out(f"TOP_N={config.TOP_N}  MIN_S={config.MIN_S}  仓位={config.S_POSITION}")
    _out(f"承接门槛={config.HANDOFF_MIN_AMOUNT / 1e8:.0f}亿  窗口={config.HIST_WINDOW_2}/{config.HIST_WINDOW_4}日")
    _out(f"执行窗口=9:{30 + config.EXEC_START}–{9 + (30 + config.EXEC_END) // 60}:"
         f"{(30 + config.EXEC_END) % 60:02d}  达标线={config.MIN_SCORE}")
    _out("=" * 60)
    if data.ak_version() == "not installed":
        _err('akshare 未安装：pip install -e .')
        return 3
    return 0


# ---------------------------------------------------------------------- pools
def cmd_pools(args: argparse.Namespace) -> int:
    from . import data, pools

    trade_date = args.date or dt.date.today()
    try:
        spot_df = data.spot(trade_date, offline=args.offline, source=args.source)
        pool_a = pools.pool_a(spot_df, config.TOP_N)
        report.print_frame(pool_a, f"池 A · 成交额前 {config.TOP_N}  [{trade_date}]")

        today_zt = data.zt_pool(trade_date, offline=args.offline)
        prev_zt = data.prev_zt_pool(trade_date, offline=args.offline)
        pool_b = pools.pool_b(prev_zt, today_zt, config.HANDOFF_MIN_AMOUNT)
        report.print_frame(pool_b, "池 B · 10 亿首板 + 次日连板")

        days = data.trade_dates(trade_date, args.history_days, offline=args.offline)
        hist = data.zt_history(days, offline=args.offline)
        pool_c = pools.pool_c(hist, trade_date)
        report.print_frame(pool_c, f"池 C · 近 {config.HIST_WINDOW_2}/{config.HIST_WINDOW_4} 日连板历史")
    except data.DataError as exc:
        _err(str(exc))
        return 3

    if pools.all_pools_empty(pool_a, pool_b, pool_c):
        _out("\n任意一层为空 → 当日不做。")
    return 0


# --------------------------------------------------------------------- screen
def cmd_screen(args: argparse.Namespace) -> int:
    """打分骨架。

    分时相关的两个输入（首次触板时间、形态）无法从日线拿到，
    这里留出接口位：接 stock_zh_a_hist_min_em 或人工输入。
    """
    from . import data, pools, score

    trade_date = args.date or dt.date.today()
    try:
        spot_df = data.spot(trade_date, offline=args.offline, source=args.source)
        pool_a = pools.pool_a(spot_df, config.TOP_N)
        s_value = pools.strength(pool_a, spot_df)
    except data.DataError as exc:
        _err(str(exc))
        return 3

    cap = pools.position_cap(s_value)
    _out(f"S 值 = {s_value}  单票仓位上限 = {cap:.0%}")
    if s_value < config.MIN_S:
        _out("S < 3 → 空仓，当日不交易。")
        return 0

    today_zt = data.zt_pool(trade_date, offline=args.offline)
    prev_zt = data.prev_zt_pool(trade_date, offline=args.offline)
    pool_b = pools.pool_b(prev_zt, today_zt, config.HANDOFF_MIN_AMOUNT)

    rows = []
    for row in today_zt.itertuples(index=False):
        detail = score.score(
            s_value=s_value,
            sector_hit=not pool_b.empty,
            in_sector=not pool_b.empty and getattr(row, "code", "") in set(pool_b["code"]),
            amount_rank=None,          # TODO 接入昨日成交额排名
            minutes_from_open=args.minutes,   # TODO 由分时数据自动计算
            form=args.form,
        )
        rows.append((getattr(row, "code", ""), getattr(row, "name", ""), detail["parts"]["env"],
                     detail["parts"]["sector"], detail["parts"]["quality"],
                     detail["parts"]["timing"], detail["parts"]["form"],
                     round(detail["total"], 1), "是" if detail["pass"] else "否"))

    headers = ["代码", "名称", "环境", "方向", "资质", "时间窗", "形态", "总分", "达标"]
    _out("")
    _out(report.render_table(headers, rows))
    _out("\n注意：触板时间与形态需人工确认后再下单；本工具不提供交易接口。")
    return 0


# -------------------------------------------------------------------- journal
def cmd_journal(args: argparse.Namespace) -> int:
    from .journal import build

    try:
        path = build(args.out, rows=args.rows)
    except RuntimeError as exc:
        _err(str(exc))
        return 3
    _out(f"已生成打卡表：{path}")
    return 0


# ----------------------------------------------------------------------- ths
def cmd_ths(args: argparse.Namespace) -> int:
    from . import ths

    return ths.sync_ths(
        trade_date=args.date,
        offline=args.offline,
        source=args.source,
        history_days=args.history_days,
        dry_run=not args.apply,
    )


# ----------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="short-term-stock-playbook", description="A 股短线打板筛选工具（研究用途）")
    parser.add_argument("-V", "--version", action="version", version=f"short-term-stock-playbook {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="环境与参数自检").set_defaults(func=cmd_doctor)

    p_pools = sub.add_parser("pools", help="构建三层标的池")
    p_pools.add_argument("--date", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD")
    p_pools.add_argument("--history-days", type=int, default=90, help="池 C 回看交易日数")
    p_pools.add_argument(
        "--offline", action="store_true", help="只用本地缓存，不联网（东财限流时用）"
    )
    p_pools.add_argument(
        "--source", default="auto", choices=["auto", "em", "sina"],
        help="行情源：auto=东财失败自动回退新浪；em=东财；sina=新浪",
    )
    p_pools.set_defaults(func=cmd_pools)

    p_screen = sub.add_parser("screen", help="当天候选打分（骨架）")
    p_screen.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p_screen.add_argument("--minutes", type=float, default=None, help="首次触板距开盘分钟数，如 25")
    p_screen.add_argument("--form", default="flat", choices=["pullback", "flat", "straight"])
    p_screen.add_argument(
        "--offline", action="store_true", help="只用本地缓存，不联网（东财限流时用）"
    )
    p_screen.add_argument(
        "--source", default="auto", choices=["auto", "em", "sina"],
        help="行情源：auto=东财失败自动回退新浪；em=东财；sina=新浪",
    )
    p_screen.set_defaults(func=cmd_screen)

    p_journal = sub.add_parser("journal", help="生成交易打卡表")
    p_journal.add_argument("--out", type=str, default=None, help="输出路径")
    p_journal.add_argument("--rows", type=int, default=120, help="预置行数")
    p_journal.set_defaults(func=cmd_journal)

    p_ths = sub.add_parser("ths", help="同步三层池到同花顺自选股分组")
    p_ths.add_argument("--date", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD")
    p_ths.add_argument("--history-days", type=int, default=90, help="池 C 回看交易日数")
    p_ths.add_argument("--offline", action="store_true", help="只用本地缓存，不联网")
    p_ths.add_argument(
        "--source", default="auto", choices=["auto", "em", "sina"],
        help="行情源：auto=东财失败自动回退新浪；em=东财；sina=新浪",
    )
    p_ths.add_argument("--apply", action="store_true",
                       help="真正写进本机同花顺自选股分组（默认 dry-run 只生成清单；写前自动备份，需先关闭同花顺）")
    p_ths.set_defaults(func=cmd_ths)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
