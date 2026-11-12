"""ths_store 同花顺文件读写的纯逻辑测试（不联网、不碰真实同花顺）。"""

from __future__ import annotations

import base64
import json

import pytest

from short_term_stock_playbook import ths_store


# --------------------------------------------------------------------------- 市场映射
def test_split_prefixed():
    assert ths_store.split_prefixed("SH600519") == ("SH", "600519")
    assert ths_store.split_prefixed("SZ000858") == ("SZ", "000858")
    assert ths_store.split_prefixed("BJ430047") == ("BJ", "430047")


def test_market_code():
    assert ths_store.market_code("SH") == "17"
    assert ths_store.market_code("SZ") == "33"
    assert ths_store.market_code("BJ") == "144"
    assert ths_store.market_code("??") is None


def test_stock_context():
    assert ths_store._stock_context(["SH600519", "SZ000858"]) == "17:600519,33:000858,,"
    # 未知市场 / 空代码被跳过
    assert ths_store._stock_context(["??123456", "SH600519"]) == "17:600519,,"


# --------------------------------------------------------------------------- 分组 ID
def test_allocate_block_id_stable():
    a = ths_store.allocate_block_id("池B承接", set())
    b = ths_store.allocate_block_id("池B承接", set())
    assert a == b
    assert a and a != "0"


def test_allocate_block_id_avoids_taken_and_zero():
    # 把 crc32 命中的值都占掉，验证会向后探测
    taken = set()
    first = ths_store.allocate_block_id("TOP5", taken)
    taken.add(first)
    second = ths_store.allocate_block_id("TOP5", taken)
    assert second != first
    assert second and second != "0"


# --------------------------------------------------------------------------- INI 解析
def test_parse_format_roundtrip():
    text = (
        "[ConfigInfo]\r\n"
        "ConfigName=stockblock_同花顺方案\r\n"
        "[BLOCK_NAME_MAP_TABLE]\r\n"
        "23=全部\r\n"
        "[BLOCK_STOCK_CONTEXT]\r\n"
        "23=17:600887,17:603288,,\r\n"
        "[encrypt_section]\r\n"
        "dnG%3D=1\r\n"
        "[@7]\r\n"
        "23=536871424"
    )
    sections = ths_store.parse_stockblock(text)
    assert ths_store.format_stockblock(sections) == text


# --------------------------------------------------------------------------- 同步端到端
def _make_fixture_store(tmp_path):
    store = tmp_path / "user"
    (store / "custom_block").mkdir(parents=True)
    (store / "stockblock.ini").write_bytes(
        (
            "[ConfigInfo]\r\n"
            "ConfigName=stockblock_同花顺方案\r\n"
            "[BLOCK_NAME_MAP_TABLE]\r\n"
            "23=全部\r\n"
            "[BLOCK_STOCK_CONTEXT]\r\n"
            "23=17:600887,17:603288,,\r\n"
            "[encrypt_section]\r\n"
            "dnG%3D=abc\r\n"
            "[@7]\r\n"
            "23=536871424"
        ).encode("gbk")
    )
    (store / "custom_block" / "0").write_bytes(b'{"sortstr":"23,"}\r\n')
    return store


def test_sync_to_store_end_to_end(tmp_path):
    store = _make_fixture_store(tmp_path)
    manifest = {
        "TOP5": ["SH600519", "SZ000858"],
        "池B承接": ["SZ000525"],
        "池C连板": [],
    }
    summary = ths_store.sync_to_store(manifest, store)

    # 摘要
    assert summary["TOP5"]["count"] == 2
    assert summary["池B承接"]["count"] == 1
    assert summary["池C连板"]["count"] == 0

    # stockblock.ini 被正确改写，且加密段原样保留
    text = (store / "stockblock.ini").read_text(encoding="gbk")
    assert "dnG%3D=abc" in text
    assert "23=全部" in text
    for group, info in summary.items():
        gid = info["id"]
        assert f"{gid}={group}" in text  # 名称映射
        assert f"{gid}=" in text  # 股票列表 + 标志段
    assert ths_store._stock_context(["SH600519", "SZ000858"]) in text
    assert "17:600887,17:603288,," in text  # 原有分组不动

    # custom_block/<十进制id> 与排序文件
    for group, info in summary.items():
        dec = str(int(info["id"], 16))
        payload = json.loads((store / "custom_block" / dec).read_text(encoding="utf-8"))
        assert payload["ln"] == base64.b64encode(group.encode("gbk")).decode("ascii")
        assert payload["xn"] == ""
        if info["count"] == 0:
            assert payload["context"] == ","  # 空组 = 单个逗号
        else:
            assert payload["context"].endswith("|") and "," in payload["context"]
    sort = json.loads((store / "custom_block" / "0").read_text(encoding="utf-8"))
    assert sort["sortstr"].startswith("23,")
    for info in summary.values():
        assert info["id"] in sort["sortstr"]

    # 备份已生成
    backups = list((store / "backup").glob("stockblock.ini.*.bak"))
    assert backups


def test_sync_to_store_reuses_existing_group_by_name(tmp_path):
    store = _make_fixture_store(tmp_path)
    # 预先放一个同名分组「池B承接」ID=EA，确保 sync 复用而不是新建
    (store / "stockblock.ini").write_bytes(
        (
            "[ConfigInfo]\r\n"
            "ConfigName=stockblock_同花顺方案\r\n"
            "[BLOCK_NAME_MAP_TABLE]\r\n"
            "EA=池B承接\r\n"
            "[BLOCK_STOCK_CONTEXT]\r\n"
            "EA=17:600000,,\r\n"
            "[encrypt_section]\r\n"
            "dnG%3D=abc\r\n"
            "[@7]\r\n"
            "EA=536871424"
        ).encode("gbk")
    )
    manifest = {"TOP5": [], "池B承接": ["SZ000525"], "池C连板": []}
    summary = ths_store.sync_to_store(manifest, store)
    assert summary["池B承接"]["id"] == "EA"
    text = (store / "stockblock.ini").read_text(encoding="gbk")
    assert "EA=池B承接" in text
    assert ths_store._stock_context(["SZ000525"]) in text


def test_sync_to_store_missing_file(tmp_path):
    with pytest.raises(ths_store.ThsStoreError):
        ths_store.sync_to_store({"TOP5": []}, tmp_path / "nope")
