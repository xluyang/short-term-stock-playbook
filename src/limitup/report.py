"""控制台表格输出与 CSV 导出（不依赖第三方宽度计算库）。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence

import pandas as pd


def _width(text: str) -> int:
    """中文按 2 列宽计算，避免表格错位。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = width - _width(text)
    gap = max(gap, 0)
    if align == "right":
        return " " * gap + str(text)
    return str(text) + " " * gap


def render_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    rows = [[("" if v is None else v) for v in row] for row in rows]
    widths = [_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _width(cell))

    numeric = {i for i, h in enumerate(headers) if any(k in str(h) for k in ("额", "价", "分", "率", "%"))}
    line = "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    out: List[str] = [line, sep]
    for row in rows:
        cells = [
            _pad(cell, widths[i], "right" if i in numeric else "left") for i, cell in enumerate(row)
        ]
        out.append("  ".join(cells))
    return "\n".join(out)


def print_frame(df: pd.DataFrame, title: str = "", limit: int = 30) -> None:
    if title:
        print(f"\n{title}")
    if df is None or df.empty:
        print("  (空)")
        return
    subset = df.head(limit)
    print(render_table(list(subset.columns), subset.itertuples(index=False, name=None)))
    if len(df) > limit:
        print(f"  ... 共 {len(df)} 行，仅显示前 {limit} 行")


def to_csv(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
