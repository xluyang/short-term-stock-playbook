"""把三层池渲染成一个可直接双击打开的本地 HTML 看板。

设计取舍
--------
1. **零外部依赖**：不引用 CDN、不引 CSS 框架，样式与脚本全部内联。
   断网、内网、手机浏览器打开都能用；文件可以随便拷给别人看。
2. **点击即跳转**：每只票是一个 ``<a target="_blank">``，指向网页版行情页。
   页面顶部可切换跳转站点（同花顺 / 东方财富 / 雪球），切换只改 href，
   不重新渲染 —— 每张卡片都预置了三套 URL。
3. **纯函数**：``build_groups`` 只吃 DataFrame、只吐数据结构，
   ``render_html`` 只吃数据结构、只吐字符串，单测不联网也不碰文件。

链接站点
--------
``ths``     https://stockpage.10jqka.com.cn/300308/     （默认，与 ths 命令同源）
``em``      https://quote.eastmoney.com/sz300308.html
``xueqiu``  https://xueqiu.com/S/SZ300308
"""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

from .config import output_dir
from .ths import market_prefix

# 站点 -> (显示名, URL 模板)。模板里 {code} 是 6 位代码，{market} 是 sh/sz/bj，{prefix} 是 SH/SZ/BJ。
LINK_SITES: Dict[str, tuple] = {
    "ths": ("同花顺", "https://stockpage.10jqka.com.cn/{code}/"),
    "em": ("东方财富", "https://quote.eastmoney.com/{market}{code}.html"),
    "xueqiu": ("雪球", "https://xueqiu.com/S/{prefix}{code}"),
}
DEFAULT_SITE = "ths"


class LinkSiteError(ValueError):
    """未知的跳转站点。"""


def stock_url(code: str, site: str = DEFAULT_SITE) -> str:
    """6 位代码 → 网页版行情页 URL。

    北交所在东财用 ``bj`` 前缀、雪球用 ``BJ`` 前缀，与 ``market_prefix`` 的
    SH/SZ/BJ 判定保持一致；代码统一补前导零，避免 000525 被写成 525。
    """
    if site not in LINK_SITES:
        raise LinkSiteError(f"未知站点 {site!r}，可选：{' / '.join(LINK_SITES)}")
    code = str(code).strip().zfill(6)
    prefix = market_prefix(code)
    return LINK_SITES[site][1].format(
        code=code,
        market=prefix.lower() if prefix != "??" else "sz",
        prefix=prefix if prefix != "??" else "SZ",
    )


# ------------------------------------------------------------------ 数据整形
def _num(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def _yi(value) -> str:
    """成交额 → 「12.3 亿」，取不到就给破折号（不要显示 nan）。"""
    out = _num(value)
    if out is None:
        return "—"
    if out >= 1e8:
        return f"{out / 1e8:.1f} 亿"
    return f"{out / 1e4:.0f} 万"


def _int_text(value, suffix: str = "") -> str:
    out = _num(value)
    return f"{int(out)}{suffix}" if out is not None else "—"


def _date_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return pd.to_datetime(value).strftime("%m-%d")
    except Exception:
        return str(value)


def _rows(frame: Optional[pd.DataFrame], kind: str) -> List[dict]:
    """DataFrame → 卡片行数据。按池类型决定展示哪些字段。"""
    if frame is None or frame.empty or "code" not in frame.columns:
        return []

    rows: List[dict] = []
    # 排序：池 A 已按成交额排名；池 B 大票在前；池 C 连板高度优先、再看最近涨停
    if kind == "b" and "amount" in frame.columns:
        frame = frame.sort_values("amount", ascending=False)
    elif kind == "c":
        keys = [c for c in ("max_boards", "last_zt") if c in frame.columns]
        if keys:
            frame = frame.sort_values(keys, ascending=False)

    for rec in frame.to_dict("records"):
        code = str(rec.get("code", "") or "").strip().zfill(6)
        name = str(rec.get("name", "") or "").strip()
        meta: List[str] = []
        badge = ""

        if kind == "a":
            meta.append(f"成交额 {_yi(rec.get('amount'))}")
            rank = _num(rec.get("amount_rank"))
            if rank is not None:
                meta.append(f"第 {int(rank)} 名")
        elif kind == "b":
            meta.append(f"成交额 {_yi(rec.get('amount'))}")
            boards = _num(rec.get("boards"))
            # 池 B 的口径是「昨日首板 → 今日连板」，boards 是昨日连板数（正常恒为 1）
            meta.append("昨日首板" if boards == 1 else f"昨日 {_int_text(boards, ' 板')}")
        else:  # pool c
            tag = str(rec.get("tag", "") or "").strip()
            badge = tag
            meta.append(f"最高 {_int_text(rec.get('max_boards'), ' 板')}")
            meta.append(f"最近涨停 {_date_text(rec.get('last_zt'))}")

        rows.append(
            {
                "code": code,
                "name": name,
                "meta": " · ".join(m for m in meta if m),
                "badge": badge,
                "search": f"{code} {name}".lower(),
            }
        )
    return rows


def build_groups(
    a: Optional[pd.DataFrame],
    b: Optional[pd.DataFrame],
    c: Optional[pd.DataFrame],
) -> List[dict]:
    """三层池 → 分组数据结构（供 render_html 消费）。"""
    return [
        {
            "id": "top5",
            "title": "池 A · TOP5",
            "note": "昨日成交额前 5 —— 环境开关，S 值由它们今日的表现决定",
            "rows": _rows(a, "a"),
        },
        {
            "id": "b",
            "title": "池 B · 承接",
            "note": "昨日 10 亿以上首板今日连板 —— 只做这个方向",
            "rows": _rows(b, "b"),
        },
        {
            "id": "c",
            "title": "池 C · 连板历史",
            "note": "C2 = 近 90 日有四连板（优先），C1 = 近 10 日有二连板",
            "rows": _rows(c, "c"),
        },
    ]


# --------------------------------------------------------------------- 渲染
_CSS = """
:root{
  --bg:#0b0f14; --panel:#121a22; --panel-2:#16202a; --line:#22303d;
  --text:#e6edf3; --muted:#8b9bab; --accent:#f6465d; --up:#f6465d;
  --down:#2ebd85; --warn:#ffb020;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--text); min-height:100vh;
  font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 64px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;justify-content:space-between}
.brand{display:flex;flex-direction:column;gap:6px}
h1{margin:0;font-size:22px;letter-spacing:.5px;font-weight:600}
h1 b{color:var(--accent);font-weight:600}
.sub{color:var(--muted);font-size:13px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{
  background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:6px 13px;font-size:12px;color:var(--muted);white-space:nowrap;
}
.chip b{color:var(--text);font-weight:600;font-size:13px}
.chip.hot b{color:var(--accent)}
.toolbar{
  position:sticky;top:10px;z-index:9;display:flex;flex-wrap:wrap;gap:10px;
  align-items:center;justify-content:space-between;
  margin:20px 0 24px;padding:12px 14px;
  background:rgba(11,15,20,.88);backdrop-filter:blur(8px);
  border:1px solid var(--line);border-radius:14px;
}
.search{
  flex:1 1 240px;min-width:200px;display:flex;align-items:center;gap:8px;
  background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;
}
.search input{
  flex:1;background:none;border:0;outline:none;color:var(--text);font-size:14px;
}
.search input::placeholder{color:#5b6b7b}
.sites{display:flex;gap:6px;align-items:center}
.sites span{color:var(--muted);font-size:12px;margin-right:2px}
.sites button{
  background:var(--panel);color:var(--muted);border:1px solid var(--line);
  border-radius:8px;padding:7px 12px;font-size:12px;cursor:pointer;
  font-family:inherit;transition:.15s;
}
.sites button:hover{color:var(--text);border-color:#33465a}
.sites button.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.banner{
  display:none;margin:0 0 20px;padding:12px 16px;border-radius:12px;font-size:13px;
  background:rgba(255,176,32,.1);border:1px solid rgba(255,176,32,.35);color:var(--warn);
}
section{margin-bottom:30px}
.sec-head{display:flex;align-items:baseline;gap:10px;margin:0 0 4px;flex-wrap:wrap}
.sec-head h2{margin:0;font-size:16px;font-weight:600;letter-spacing:.4px;white-space:nowrap}
.sec-head .count{
  font-size:12px;color:var(--muted);background:var(--panel);
  border:1px solid var(--line);border-radius:6px;padding:2px 8px;white-space:nowrap;
}
.sec-note{font-size:12px;color:var(--muted);margin:0 0 12px;line-height:1.6}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(206px,1fr));gap:10px}
.stock{
  position:relative;display:flex;flex-direction:column;gap:5px;
  padding:13px 14px;border-radius:12px;text-decoration:none;
  background:var(--panel);border:1px solid var(--line);
  transition:transform .12s,border-color .12s,background .12s;
}
.stock:hover{transform:translateY(-2px);border-color:var(--accent);background:var(--panel-2)}
.stock:hover .go{opacity:1;transform:translate(0,0)}
.stock .top{display:flex;align-items:center;gap:8px;justify-content:space-between}
.stock .code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--muted)}
.stock .name{font-size:15px;font-weight:600;color:var(--text);line-height:1.3}
.stock .meta{font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.badge{
  font-size:10px;font-weight:700;letter-spacing:.5px;border-radius:5px;
  padding:1px 6px;border:1px solid transparent;
}
.badge.C2{background:rgba(246,70,93,.16);color:#ff8296;border-color:rgba(246,70,93,.4)}
.badge.C1{background:rgba(88,166,255,.14);color:#79bbff;border-color:rgba(88,166,255,.35)}
.go{
  position:absolute;right:10px;bottom:10px;font-size:10.5px;line-height:1;
  color:#fff;background:var(--accent);border-radius:6px;padding:3px 7px;
  opacity:0;transform:translate(-4px,0);transition:.15s;
}
kbd{
  font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text);
  background:var(--panel-2);border:1px solid var(--line);border-bottom-width:2px;
  border-radius:4px;padding:0 5px;margin:0 1px;
}
.empty{color:var(--muted);font-size:13px;padding:14px 16px;border:1px dashed var(--line);border-radius:12px}
footer{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);color:#66757f;font-size:12px;line-height:1.9}
footer b{color:var(--muted)}
.hidden{display:none !important}
@media(max-width:520px){
  .wrap{padding:18px 14px 48px}
  h1{font-size:19px}
  .grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
  .stock{padding:11px 12px}
  .stock .name{font-size:14px}
}
"""

_JS = """
(function(){
  var current = 'ths';
  var links = Array.prototype.slice.call(document.querySelectorAll('a.stock'));

  function applySite(site){
    current = site;
    links.forEach(function(a){
      var url = a.dataset[site];
      if(url){ a.href = url; }
    });
    Array.prototype.forEach.call(document.querySelectorAll('.sites button'), function(b){
      b.classList.toggle('on', b.dataset.site === site);
    });
  }

  document.querySelectorAll('.sites button').forEach(function(btn){
    btn.addEventListener('click', function(){ applySite(btn.dataset.site); });
  });

  var input = document.getElementById('q');
  var banner = document.getElementById('no-hit');
  input.addEventListener('input', function(){
    var q = input.value.trim().toLowerCase();
    var hits = 0;
    document.querySelectorAll('section').forEach(function(sec){
      var n = 0;
      sec.querySelectorAll('a.stock').forEach(function(a){
        var hit = !q || a.dataset.search.indexOf(q) !== -1;
        a.classList.toggle('hidden', !hit);
        if(hit) n++;
      });
      sec.classList.toggle('hidden', q && n === 0);
      hits += n;
    });
    banner.style.display = (q && hits === 0) ? 'block' : 'none';
  });

  document.addEventListener('keydown', function(e){
    if(e.key === '/' && document.activeElement !== input){ e.preventDefault(); input.focus(); }
    if(e.key === 'Escape'){ input.value=''; input.dispatchEvent(new Event('input')); input.blur(); }
  });

  applySite(current);
})();
"""


def _render_card(row: dict) -> str:
    attrs = " ".join(
        f'data-{site}="{html.escape(stock_url(row["code"], site))}"' for site in LINK_SITES
    )
    badge = f'<span class="badge {html.escape(row["badge"])}">{html.escape(row["badge"])}</span>' if row["badge"] else ""
    return (
        f'<a class="stock" href="{html.escape(stock_url(row["code"]))}" {attrs} '
        f'data-search="{html.escape(row["search"])}" target="_blank" rel="noopener noreferrer">'
        f'<span class="top"><span class="code">{html.escape(row["code"])}</span>{badge}</span>'
        f'<span class="name">{html.escape(row["name"])}</span>'
        f'<span class="meta">{html.escape(row["meta"])}</span>'
        f'<span class="go">打开 ↗</span>'
        f"</a>"
    )


def _render_section(group: dict) -> str:
    rows = group["rows"]
    body = (
        '<div class="grid">' + "".join(_render_card(r) for r in rows) + "</div>"
        if rows
        else '<div class="empty">今日空池 —— 按模型规则，任意一层为空则当日不做。</div>'
    )
    return (
        f'<section id="{html.escape(group["id"])}">'
        f'<div class="sec-head"><h2>{html.escape(group["title"])}</h2>'
        f'<span class="count">{len(rows)} 只</span></div>'
        f'<div class="sec-note">{html.escape(group["note"])}</div>'
        f"{body}</section>"
    )


def render_html(
    groups: Sequence[dict],
    trade_date: Optional[dt.date] = None,
    s_value: Optional[int] = None,
    position_cap: Optional[float] = None,
    site: str = DEFAULT_SITE,
) -> str:
    """分组数据 → 整页 HTML 字符串（自包含，无外链资源）。"""
    day = trade_date or dt.date.today()
    total = sum(len(g["rows"]) for g in groups)
    empty = any(len(g["rows"]) == 0 for g in groups)

    chips = [f'<span class="chip">标的 <b>{total}</b> 只</span>']
    if s_value is not None:
        hot = " hot" if s_value >= 3 else ""
        chips.append(f'<span class="chip{hot}">S 值 <b>{int(s_value)}</b></span>')
    if position_cap:
        chips.append(f'<span class="chip">单票上限 <b>{position_cap:.0%}</b></span>')
    chips.append(f'<span class="chip">数据日 <b>{day:%Y-%m-%d}</b></span>')

    buttons = []
    for key, (label, _) in LINK_SITES.items():
        active = " on" if key == site else ""
        buttons.append(f'<button data-site="{key}" class="{active.strip()}">{html.escape(label)}</button>')
    site_buttons = "".join(buttons)

    banner = (
        '<div class="banner" style="display:block">'
        "任意一层为空 → 按模型规则当日不做，下面的池仅供参考。</div>"
        if empty
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>三层标的池 {day:%Y-%m-%d} · short-term-stock-playbook</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <h1>三层标的池 · <b>{day:%Y-%m-%d}</b></h1>
      <div class="sub">点击个股打开网页版行情 · 顶部切换跳转站点 · 按 <kbd>/</kbd> 搜索</div>
    </div>
    <div class="chips">{"".join(chips)}</div>
  </header>

  <div class="toolbar">
    <label class="search">
      <span style="color:#5b6b7b">⌕</span>
      <input id="q" type="search" placeholder="搜代码或名称，如 300308 / 中际" autocomplete="off">
    </label>
    <div class="sites"><span>跳转</span>{site_buttons}</div>
  </div>

  {banner}
  <div class="banner" id="no-hit">没有匹配的标的，换个关键词试试。</div>

  {"".join(_render_section(g) for g in groups)}

  <footer>
    <b>免责声明</b>：本页由 short-term-stock-playbook 生成，仅供个人研究复盘，<b>不构成投资建议</b>，不含下单接口。<br>
    数据来自 akshare 公开接口，准确性不作保证；打板为高风险交易方式，亏损自负。<br>
    生成时间 {dt.datetime.now():%Y-%m-%d %H:%M} · 模型参数见 config.py
  </footer>
</div>
<script>{_JS}</script>
</body>
</html>
"""


def write_html(
    a: Optional[pd.DataFrame],
    b: Optional[pd.DataFrame],
    c: Optional[pd.DataFrame],
    trade_date: Optional[dt.date] = None,
    s_value: Optional[int] = None,
    position_cap: Optional[float] = None,
    site: str = DEFAULT_SITE,
    path: Optional[Path] = None,
) -> Path:
    """渲染并落盘；默认 output/playbook_YYYYMMDD.html。"""
    day = trade_date or dt.date.today()
    if site not in LINK_SITES:
        raise LinkSiteError(f"未知站点 {site!r}，可选：{' / '.join(LINK_SITES)}")
    dest = path or output_dir() / f"playbook_{day:%Y%m%d}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        render_html(
            build_groups(a, b, c),
            trade_date=day,
            s_value=s_value,
            position_cap=position_cap,
            site=site,
        ),
        encoding="utf-8",
    )
    return dest
