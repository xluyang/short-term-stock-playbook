"""web 看板的纯逻辑测试（不联网、不写文件）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from short_term_stock_playbook import web


def test_stock_url_all_sites():
    assert web.stock_url("300308", "ths") == "https://stockpage.10jqka.com.cn/300308/"
    assert web.stock_url("600519", "em") == "https://quote.eastmoney.com/sh600519.html"
    assert web.stock_url("000001", "em") == "https://quote.eastmoney.com/sz000001.html"
    assert web.stock_url("830799", "xueqiu") == "https://xueqiu.com/S/BJ830799"
    # 前导零被吃掉时仍按深市补零
    assert web.stock_url("525", "xueqiu") == "https://xueqiu.com/S/SZ000525"


def test_stock_url_unknown_site():
    with pytest.raises(web.LinkSiteError):
        web.stock_url("300308", "bogus")


def test_build_groups_counts_and_fields():
    a = pd.DataFrame({"code": ["300308"], "name": ["中际旭创"], "amount": [1.2e10], "amount_rank": [1]})
    b = pd.DataFrame({"code": ["000678"], "name": ["襄阳轴承"], "amount": [1.5e9], "boards": [2]})
    c = pd.DataFrame(
        {
            "code": ["000017"],
            "name": ["深中华A"],
            "tag": ["C2"],
            "max_boards": [4],
            "last_zt": [pd.Timestamp("2026-11-05")],
        }
    )
    groups = web.build_groups(a, b, c)
    assert [g["id"] for g in groups] == ["top5", "b", "c"]
    assert [len(g["rows"]) for g in groups] == [1, 1, 1]

    top = groups[0]["rows"][0]
    assert top["code"] == "300308"
    assert "120.0 亿" in top["meta"]
    assert "第 1 名" in top["meta"]

    # 池 B 的 boards 是「昨日连板数」，1 板时直接说「昨日首板」
    assert "昨日 2 板" in groups[1]["rows"][0]["meta"]
    assert groups[2]["rows"][0]["badge"] == "C2"
    assert "最高 4 板" in groups[2]["rows"][0]["meta"]


def test_build_groups_empty_inputs():
    groups = web.build_groups(None, pd.DataFrame(), None)
    assert [g["rows"] for g in groups] == [[], [], []]


def test_render_html_contains_links_and_sites():
    a = pd.DataFrame({"code": ["300308"], "name": ["中际旭创"], "amount": [1.2e10], "amount_rank": [1]})
    html = web.render_html(web.build_groups(a, None, None), trade_date=dt.date(2026, 11, 12), s_value=4)
    # 三套跳转 URL 都预置在卡片上，切换站点只改 href
    assert "https://stockpage.10jqka.com.cn/300308/" in html
    assert "https://quote.eastmoney.com/sz300308.html" in html
    assert "https://xueqiu.com/S/SZ300308" in html
    assert 'target="_blank"' in html
    assert "2026-11-12" in html
    assert "S 值" in html
    # 空池提示 & 当日不做横幅
    assert "任意一层为空" in html


def test_render_html_escapes_name():
    a = pd.DataFrame({"code": ["000001"], "name": ["<script>x</script>"], "amount": [1e9], "amount_rank": [3]})
    html = web.render_html(web.build_groups(a, None, None))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html


def test_write_html(tmp_path):
    a = pd.DataFrame({"code": ["300308"], "name": ["中际旭创"], "amount": [1.2e10], "amount_rank": [1]})
    dest = tmp_path / "p.html"
    out = web.write_html(a, None, None, trade_date=dt.date(2026, 11, 12), path=dest)
    assert out == dest
    assert dest.stat().st_size > 1000
    with pytest.raises(web.LinkSiteError):
        web.write_html(a, None, None, site="nope", path=tmp_path / "q.html")
