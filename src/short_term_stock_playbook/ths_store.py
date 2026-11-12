"""同花顺自选股分组的本地文件读写（覆盖式同步）。

同花顺 PC 客户端把「自选股分组」存在用户数据目录，本模块只做一件事：
把 ``ths.build_manifest`` 产出的三层池（TOP5 / 池B承接 / 池C连板）**覆盖**写进
对应的三个分组，其余分组、加密段、自选股总表一律不动。

同花顺本地有两份互相镜像的存储：

1. ``stockblock.ini`` —— 经典 GBK INI（``\\r\\n`` 换行、无尾换行）：

   * ``[BLOCK_NAME_MAP_TABLE]``   分组 ID(十六进制) -> 分组名(GBK)
   * ``[BLOCK_STOCK_CONTEXT]``   分组 ID -> ``市场:代码,市场:代码,...,,``
   * ``[encrypt_section]``       条件选股的加密段（原样保留，绝不改）
   * ``[@7]``                    分组 ID -> 显示标志（统一 536871424）

2. ``custom_block/<十进制id>`` —— 较新的 JSON（UTF-8、``\\r\\n`` 结尾）：

   ``{"context":"代码|代码|,市场|市场|","ln":"<base64(GBK 名)>","xn":""}``

   ``custom_block/0`` 存分组排序 ``{"sortstr":"23,25,...,"}``。

市场码：17=沪、33=深、144=北交所（其余市场不在涨停池内，忽略）。

安全约定：
* 默认不写（由上层 ``--apply`` 控制），写入前先做带时间戳的备份；
* 分组 ID 按「组名反查已有 ID」复用，查不到才用 crc32 派生稳定新 ID，并避开
  已占用 ID 与保留字 ``0``（``custom_block/0`` 是排序文件，不是分组）。
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import zlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# 市场前缀 -> 同花顺市场码（涨停池只可能出现沪/深/北）。
THS_MARKET = {"SH": "17", "SZ": "33", "BJ": "144"}

# [@7] 里所有现有分组的统一标志（0x20000000），新分组沿用。
BLOCK_FLAG = "536871424"

# 与 ths.GROUP_NAMES 保持一致：覆盖这三组，而不是每天新建。
GROUP_NAMES = ("TOP5", "池B承接", "池C连板")

# stockblock.ini 中需要改写的三个段名。
_SECTION_NAMES = "[BLOCK_NAME_MAP_TABLE]"
_SECTION_STOCKS = "[BLOCK_STOCK_CONTEXT]"
_SECTION_FLAGS = "[@7]"

# 保留字：custom_block/0 是排序文件，不能被当作分组 ID。
_RESERVED_IDS = {"0"}


class ThsStoreError(RuntimeError):
    """同花顺数据定位 / 写入失败。"""


# --------------------------------------------------------------------------
# INI 解析与序列化
# --------------------------------------------------------------------------
def parse_stockblock(text: str) -> List[Tuple[Optional[str], List[str]]]:
    """把 INI 文本解析为 ``[(段名, [原始行...]), ...]``，保留顺序与未识别内容。

    ``段名`` 为 None 表示文件开头的裸行（正常不存在）。
    """
    sections: List[Tuple[Optional[str], List[str]]] = []
    header: Optional[str] = None
    lines: List[str] = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("[") and line.endswith("]"):
            if header is not None or lines:
                sections.append((header, lines))
            header = line
            lines = []
        else:
            lines.append(line)
    if header is not None or lines:
        sections.append((header, lines))
    return sections


def format_stockblock(sections: List[Tuple[Optional[str], List[str]]]) -> str:
    """与 parse_stockblock 互逆：按原顺序拼回 INI 文本（\\r\\n，无尾换行）。"""
    out: List[str] = []
    for header, lines in sections:
        if header is not None:
            out.append(header)
        out.extend(lines)
    return "\r\n".join(out)


def _section_index(
    sections: List[Tuple[Optional[str], List[str]]], name: str
) -> int:
    for i, (header, _) in enumerate(sections):
        if header == name:
            return i
    return -1


def _kv_parse(lines: Iterable[str]) -> Dict[str, str]:
    """把 ``k=v`` 行解析为有序 dict；非 ``k=v`` 行丢弃（目标段全部是键值对）。"""
    result: Dict[str, str] = {}
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _kv_format(mapping: Dict[str, str]) -> List[str]:
    return [f"{key}={value}" for key, value in mapping.items()]


# --------------------------------------------------------------------------
# 分组 ID 与市场映射
# --------------------------------------------------------------------------
def split_prefixed(code: str) -> Tuple[str, str]:
    """``SH600519`` -> (``SH``, ``600519``)。未知前缀原样返回，交给调用方过滤。"""
    code = str(code).strip()
    prefix, rest = code[:2], code[2:]
    return prefix, rest


def market_code(prefix: str) -> Optional[str]:
    """市场前缀 -> 同花顺市场码；未知返回 None。"""
    return THS_MARKET.get(prefix)


def allocate_block_id(name: str, taken: Iterable[str]) -> str:
    """为一组名派生稳定十六进制分组 ID，避开已占用 ID 与保留字 ``0``。"""
    occupied = set(taken) | _RESERVED_IDS
    h = zlib.crc32(name.encode("gbk")) & 0xFFFF
    while True:
        candidate = format(h, "X")  # 无前导零，与现有 "23"/"EA"/"14C" 风格一致
        if candidate and candidate not in occupied:
            return candidate
        h = (h + 1) & 0xFFFF


def _stock_context(prefixed_codes: Iterable[str]) -> str:
    """``["SH600519", "SZ000858"]`` -> ``"17:600519,33:000858,,"``。"""
    pairs = []
    for raw in prefixed_codes:
        prefix, code = split_prefixed(raw)
        mkt = market_code(prefix)
        if mkt is not None and code:
            pairs.append(f"{mkt}:{code}")
    return ",".join(pairs) + ",,"


# --------------------------------------------------------------------------
# 备份与写入
# --------------------------------------------------------------------------
def _backup(path: Path) -> None:
    """写入前做带时间戳的副本，放 ``<同目录>/backup/`` 下。"""
    if not path.exists():
        return
    backup_dir = path.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    (backup_dir / f"{path.name}.{stamp}.bak").write_bytes(path.read_bytes())


def _write_json_line(path: Path, payload: dict) -> None:
    """紧凑 JSON + 尾部 \\r\\n，与同花顺现有 custom_block 文件一致。"""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_bytes(text.encode("utf-8") + b"\r\n")


def _update_custom_blocks(
    store_dir: Path, summary: Dict[str, dict], manifest: Dict[str, List[str]]
) -> None:
    cb = store_dir / "custom_block"
    cb.mkdir(parents=True, exist_ok=True)

    new_ids: List[str] = []
    for group in GROUP_NAMES:
        info = summary[group]
        gid = info["id"]
        dec_id = str(int(gid, 16))
        new_ids.append(gid)

        codes: List[str] = []
        markets: List[str] = []
        for raw in manifest.get(group, []):
            prefix, code = split_prefixed(raw)
            mkt = market_code(prefix)
            if mkt is not None and code:
                codes.append(code)
                markets.append(mkt)
        # 空组 context 就是单个逗号（与同花顺已删除/空组的表示一致），非空才是 `代码|市场|`。
        if codes:
            context = "|".join(codes) + "|" + "," + "|".join(markets) + "|"
        else:
            context = ","
        ln = base64.b64encode(group.encode("gbk")).decode("ascii")
        payload = {"context": context, "ln": ln, "xn": ""}

        target = cb / dec_id
        _backup(target)
        _write_json_line(target, payload)

    sort_path = cb / "0"
    sortstr: List[str] = []
    if sort_path.exists():
        try:
            data = json.loads(sort_path.read_text(encoding="utf-8"))
            sortstr = [x for x in data.get("sortstr", "").split(",") if x]
        except (json.JSONDecodeError, UnicodeDecodeError):
            sortstr = []
    for gid in new_ids:
        if gid not in sortstr:
            sortstr.append(gid)
    _backup(sort_path)
    _write_json_line(sort_path, {"sortstr": ",".join(sortstr) + ","})


# --------------------------------------------------------------------------
# 同步主逻辑
# --------------------------------------------------------------------------
def sync_to_store(
    manifest: Dict[str, List[str]], store_dir: Path
) -> Dict[str, dict]:
    """把 manifest 的三组覆盖写进 ``store_dir`` 下的同花顺文件，返回变更摘要。

    不触碰：``[encrypt_section]``、其它分组、``SelfStockInfo.json`` / ``D7DD``
    自选股总表。写入前对每个改动文件做带时间戳备份。
    """
    sb_path = store_dir / "stockblock.ini"
    if not sb_path.exists():
        raise ThsStoreError(f"未找到同花顺分组文件：{sb_path}")

    sections = parse_stockblock(sb_path.read_text(encoding="gbk"))

    # 取（或新建）三个目标段，其余段原样保留。
    names = _kv_parse(_section_lines(sections, _SECTION_NAMES))
    stocks = _kv_parse(_section_lines(sections, _SECTION_STOCKS))
    flags = _kv_parse(_section_lines(sections, _SECTION_FLAGS))

    taken = set(names) | set(stocks) | set(flags)
    summary: Dict[str, dict] = {}

    for group in GROUP_NAMES:
        codes = manifest.get(group, [])
        # 优先按组名复用已有分组 ID，保证重复运行更新而非新建。
        gid = next((k for k, v in names.items() if v == group), None)
        if gid is None:
            gid = allocate_block_id(group, taken)
            taken.add(gid)
        names[gid] = group
        stocks[gid] = _stock_context(codes)
        flags[gid] = BLOCK_FLAG
        summary[group] = {"id": gid, "count": len(codes)}

    _set_section_lines(sections, _SECTION_NAMES, _kv_format(names))
    _set_section_lines(sections, _SECTION_STOCKS, _kv_format(stocks))
    _set_section_lines(sections, _SECTION_FLAGS, _kv_format(flags))

    _backup(sb_path)
    sb_path.write_bytes(format_stockblock(sections).encode("gbk"))

    _update_custom_blocks(store_dir, summary, manifest)

    return summary


def _section_lines(
    sections: List[Tuple[Optional[str], List[str]]], name: str
) -> List[str]:
    idx = _section_index(sections, name)
    if idx >= 0:
        return sections[idx][1]
    return []


def _set_section_lines(
    sections: List[Tuple[Optional[str], List[str]]], name: str, lines: List[str]
) -> None:
    idx = _section_index(sections, name)
    if idx >= 0:
        sections[idx] = (name, lines)
    else:
        sections.append((name, lines))


# --------------------------------------------------------------------------
# 定位同花顺
# --------------------------------------------------------------------------
_INSTALL_CANDIDATES = (
    Path("C:/同花顺软件/同花顺"),
    Path("C:/同花顺远航版"),
    Path("C:/同花顺"),
    Path("C:/Program Files/同花顺"),
    Path("C:/Program Files (x86)/同花顺"),
)


def locate_ths_home() -> Optional[Path]:
    """定位同花顺安装目录（含 ``hexin.exe`` 或 子目录含 ``stockblock.ini``）。"""
    hits: List[Path] = []
    for root in (Path("C:/"), Path("D:/")):
        try:
            for p in root.glob("*同花顺*"):
                if p.is_dir():
                    hits.append(p)
        except OSError:
            continue
    for p in _INSTALL_CANDIDATES:
        if p.is_dir() and p not in hits:
            hits.append(p)

    for p in hits:
        if (p / "hexin.exe").is_file():
            return p
    for p in hits:
        if any(p.glob("*/stockblock.ini")):
            return p
    return None


def locate_user_dir(ths_home: Path) -> Optional[Path]:
    """在安装目录下找活跃用户数据目录（含 ``stockblock.ini``，mtime 最新优先）。

    排除名称含 ``guest`` 的访客目录，除非只有访客目录可用。
    """
    candidates: List[Path] = []
    try:
        for d in ths_home.iterdir():
            if d.is_dir() and (d / "stockblock.ini").is_file():
                candidates.append(d)
    except OSError:
        pass

    if not candidates:
        for d in ths_home.rglob("stockblock.ini"):
            parent = d.parent
            if parent not in candidates:
                candidates.append(parent)

    non_guest = [d for d in candidates if "guest" not in d.name.lower()]
    pool = non_guest or candidates
    if not pool:
        return None
    return max(pool, key=lambda d: (d / "stockblock.ini").stat().st_mtime)


def store_adapter(manifest: Dict[str, List[str]]) -> None:
    """``sync_ths`` 的默认 adapter：定位同花顺并写三组。失败抛 ThsStoreError。"""
    ths_home = locate_ths_home()
    if ths_home is None:
        raise ThsStoreError("未找到同花顺安装目录（含 hexin.exe 的目录）")
    user_dir = locate_user_dir(ths_home)
    if user_dir is None:
        raise ThsStoreError(f"在 {ths_home} 下未找到用户数据目录（stockblock.ini）")
    summary = sync_to_store(manifest, user_dir)
    print(f"\n已写入同花顺自选股分组：{user_dir}")
    for group in GROUP_NAMES:
        info = summary[group]
        print(f"  {group:<6} {info['count']:>2} 只  (分组ID {info['id']})")
