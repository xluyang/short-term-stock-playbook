"""生成交易日打卡表（xlsx）。

用法：
    short-term-stock-playbook journal                      # 输出到 output/journal_<日期>.xlsx
    short-term-stock-playbook journal --out 我的打卡表.xlsx

设计说明
--------
- 打卡页只填「原始数据」，总分 / 溢价 / 贡献三列是公式，不要手改。
- 统计页全部用公式引用打卡页，随填随算，不含宏。
- 不预置任何交易记录，避免把个人数据带进仓库。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

SHEET_JOURNAL = "打卡"
SHEET_STATS = "统计"
SHEET_HELP = "说明"

HEADERS = [
    ("序号", 6),
    ("日期", 12),
    ("代码", 10),
    ("名称", 12),
    ("方向/板块", 12),
    ("S值", 6),
    ("方向分", 8),
    ("资质分", 8),
    ("时间窗分", 10),
    ("形态分", 8),
    ("总分", 8),
    ("触板时间", 10),
    ("封单额(万)", 11),
    ("买入价", 9),
    ("是否封住", 9),
    ("次日开盘价", 11),
    ("隔日溢价", 10),
    ("仓位", 8),
    ("账户贡献", 10),
    ("备注", 24),
]

PERCENT_COLS = {"隔日溢价", "仓位", "账户贡献"}
CENTER_COLS = {"序号", "日期", "代码", "S值", "方向分", "资质分", "时间窗分", "形态分", "总分", "是否封住"}

HELP_LINES = [
    ("短线打板选股模型 · 交易打卡表", True),
    ("", False),
    ("一、填写规则", True),
    ("1. 每笔交易填一行，只填白底列（S值/方向分/资质分/时间窗分/形态分、买入价、是否封住、次日开盘价、仓位）。", False),
    ("2. 总分、隔日溢价、账户贡献是公式，不要手工覆盖。", False),
    ("3. 总分公式：S值/5×30 + 方向分 + 资质分 + 时间窗分 + 形态分，满分 100。", False),
    ("4. 总分 < 70 的笔次不要下单；若已下单，在备注里写「违规」。", False),
    ("", False),
    ("二、各分项口径", True),
    ("S值：昨日成交额前五中，今日上涨的只数（0–5）。5→30分，4→24分，3→15分，≤2→0分。", False),
    ("方向分：池B命中且个股属该方向→25；仅方向命中→15；无→0。", False),
    ("资质分：昨日成交额排名前20→20；前50→12；其余→5。", False),
    ("时间窗分：9:50–10:10 首次触板→15；10:10–10:30→10；窗口外→0。", False),
    ("形态分：回踩/下杀后拉起→10；平开震荡后上攻→6；直线拉→0。", False),
    ("仓位：由总分决定（70–79→10%，80–89→20%，≥90→30%），且不超过 S 值给出的上限。", False),
    ("", False),
    ("三、统计口径", True),
    ("封板率 = 封住笔数 / 总笔数，目标 > 65%。", False),
    ("胜率 = 隔日溢价 > 0 的占比，目标 > 55%。", False),
    ("盈亏比 = 平均盈利 / |平均亏损|，目标 > 1.5。", False),
    ("至少 100 笔、跨 3 个月、含一次退潮期，结论才有效。", False),
    ("", False),
    ("四、免责声明", True),
    ("本表仅用于个人交易记录与研究，不构成投资建议。策略模型详见 docs/model.md。", False),
]


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('需要 openpyxl：pip install -e ".[journal]"') from exc
    return Workbook, Alignment, Border, Font, PatternFill, Side, get_column_letter, DataValidation


def default_path() -> Path:
    from .config import output_dir

    return output_dir() / f"journal_{dt.date.today():%Y%m%d}.xlsx"


def build(path: Optional[Path] = None, rows: int = 120) -> Path:
    """生成打卡表并返回路径。"""
    Workbook, Alignment, Border, Font, PatternFill, Side, get_column_letter, DataValidation = (
        _require_openpyxl()
    )

    target = Path(path) if path else default_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(color="FFFFFF", bold=True, size=11)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_JOURNAL

    for idx, (title, width) in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=idx, value=title)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = center
        cell.border = border
        ws.column_dimensions[get_column_letter(idx)].width = width

    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "B2"

    for r in range(2, rows + 2):
        ws.cell(row=r, column=1, value=r - 1).alignment = center
        for c in range(1, len(HEADERS) + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = border
            if c == 1:
                continue
            cell.alignment = center if HEADERS[c - 1][0] in CENTER_COLS else left
            name = HEADERS[c - 1][0]
            if name in PERCENT_COLS:
                cell.number_format = "0.00%"
            elif name in ("买入价", "次日开盘价"):
                cell.number_format = "0.00"

        ws.cell(row=r, column=11, value=(
            f'=IF(COUNT(F{r}:J{r})=0,"",F{r}/5*30+G{r}+H{r}+I{r}+J{r})'
        )).number_format = "0.0"
        ws.cell(row=r, column=17, value=(
            f'=IF(OR($N{r}="",$P{r}=""),"",($P{r}-$N{r})/$N{r})'
        )).number_format = "0.00%"
        ws.cell(row=r, column=19, value=(
            f'=IF(OR($Q{r}="",$R{r}=""),"",$Q{r}*$R{r})'
        )).number_format = "0.00%"

    dv = DataValidation(type="list", formula1='"是,否"', allow_blank=True)
    dv.error = "只能填 是 或 否"
    dv.errorTitle = "输入有误"
    ws.add_data_validation(dv)
    dv.add(f"O2:O{rows + 1}")

    ws.auto_filter.ref = f"A1:T{rows + 1}"

    # ---------------- 统计页 ----------------
    st = wb.create_sheet(SHEET_STATS)
    st.column_dimensions["A"].width = 16
    st.column_dimensions["B"].width = 16
    st.column_dimensions["C"].width = 32

    st["A1"] = "统计（随打卡页自动更新）"
    st["A1"].font = Font(bold=True, size=13)

    def stat_row(row: int, label: str, formula: str, note: str, fmt: Optional[str] = None) -> None:
        st.cell(row=row, column=1, value=label)
        cell = st.cell(row=row, column=2, value=formula)
        st.cell(row=row, column=3, value=note)
        if fmt:
            cell.number_format = fmt
        for c in range(1, 4):
            st.cell(row=row, column=c).border = border
        st.cell(row=row, column=2).alignment = center

    j = SHEET_JOURNAL
    rng_k = f"'{j}'!$K$2:$K${rows + 1}"
    rng_n = f"'{j}'!$N$2:$N${rows + 1}"
    rng_o = f"'{j}'!$O$2:$O${rows + 1}"
    rng_q = f"'{j}'!$Q$2:$Q${rows + 1}"
    rng_s = f"'{j}'!$S$2:$S${rows + 1}"

    stat_row(3, "总笔数", f"=COUNT({rng_n})", "已填买入价的笔数")
    stat_row(4, "达标笔数", f'=COUNTIF({rng_k},">=70")', "总分 ≥ 70")
    stat_row(5, "违规笔数", f'=COUNTIF({rng_k},"<70")', "总分 < 70 仍下单")
    stat_row(6, "封板率", f'=IFERROR(COUNTIF({rng_o},"是")/COUNTA({rng_o}),"")', "目标 > 65%", "0.0%")
    stat_row(7, "胜率", f'=IFERROR(COUNTIF({rng_q},">0")/COUNT({rng_q}),"")', "目标 > 55%", "0.0%")
    stat_row(8, "平均溢价", f'=IFERROR(AVERAGE({rng_q}),"")', "目标 > 2%", "0.00%")
    stat_row(9, "平均盈利", f'=IFERROR(AVERAGEIF({rng_q},">0"),"")', "", "0.00%")
    stat_row(10, "平均亏损", f'=IFERROR(AVERAGEIF({rng_q},"<0"),"")', "", "0.00%")
    stat_row(11, "盈亏比", '=IFERROR(B9/ABS(B10),"")', "目标 > 1.5", "0.00")
    stat_row(12, "累计贡献", f'=IFERROR(SUM({rng_s}),"")', "按仓位加权的收益合计", "0.00%")
    stat_row(13, "平均得分", f'=IFERROR(AVERAGE({rng_k}),"")', "衡量执行质量", "0.0")

    # ---------------- 说明页 ----------------
    hp = wb.create_sheet(SHEET_HELP)
    hp.column_dimensions["A"].width = 120
    for i, (text, bold) in enumerate(HELP_LINES, start=1):
        cell = hp.cell(row=i, column=1, value=text)
        cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=False)
        if bold:
            cell.font = Font(bold=True, size=12)

    wb.save(target)
    return target
