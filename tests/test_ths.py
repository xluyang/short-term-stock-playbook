"""ths 分组同步的纯逻辑测试。"""

from __future__ import annotations

import pandas as pd

from short_term_stock_playbook import ths


def test_market_prefix():
    assert ths.market_prefix("600519") == "SH"
    assert ths.market_prefix("688111") == "SH"
    assert ths.market_prefix("000001") == "SZ"
    assert ths.market_prefix("300750") == "SZ"
    assert ths.market_prefix("430047") == "BJ"
    assert ths.market_prefix("830799") == "BJ"
    # 前导零被吃掉时按 000525 判断为深市
    assert ths.market_prefix("525") == "SZ"


def test_build_manifest():
    a = pd.DataFrame({"code": ["600519", "000858"], "name": ["贵州茅台", "五粮液"]})
    b = pd.DataFrame({"code": ["000525"], "name": ["红日药业"]})
    c = pd.DataFrame()  # 空池
    m = ths.build_manifest(a, b, c)
    assert m["TOP5"] == ["SH600519", "SZ000858"]
    assert m["池B承接"] == ["SZ000525"]
    assert m["池C连板"] == []


def test_build_manifest_empty_inputs():
    m = ths.build_manifest(None, None, None)
    assert m == {"TOP5": [], "池B承接": [], "池C连板": []}
