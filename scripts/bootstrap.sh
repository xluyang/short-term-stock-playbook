#!/usr/bin/env bash
# limitup-playbook bootstrap (macOS / Linux)
#
# 在仓库内建立独立虚拟环境 .venv 并安装全部依赖，不触碰系统 site-packages。
# 重复执行安全：已有 .venv 复用，pip 只补缺的包。
#
#   ./scripts/bootstrap.sh            正常安装
#   ./scripts/bootstrap.sh --recreate 删除 .venv 重建
#   PYTHON=/usr/bin/python3.11 ./scripts/bootstrap.sh
#
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
RECREATE=0

for arg in "$@"; do
    case "$arg" in
        --recreate) RECREATE=1 ;;
        -h|--help)  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $arg" >&2; exit 2 ;;
    esac
done

c_cyan='\033[36m'; c_green='\033[32m'; c_dim='\033[2m'; c_yellow='\033[33m'; c_off='\033[0m'
step() { printf "${c_cyan}==> %s${c_off}\n" "$1"; }
ok()   { printf "${c_dim}    %s${c_off}\n" "$1"; }
warn() { printf "${c_yellow}!!  %s${c_off}\n" "$1"; }

echo
printf "${c_green}limitup-playbook bootstrap${c_off}\n"
echo "  repo : $ROOT"
echo "  venv : $VENV"
echo

# --------------------------------------------------------------- 1. 解释器
step "定位 Python 3.9-3.13"
usable() {
    [ -x "$1" ] || return 1
    "$1" - <<'PYEOF' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info[:2] >= (3, 9) and sys.version_info[:2] <= (3, 13) else 1)
PYEOF
}

CANDIDATE="${PYTHON:-}"
if [ -z "$CANDIDATE" ]; then
    for c in python3.11 python3.12 python3.10 python3.13 python3; do
        if command -v "$c" >/dev/null 2>&1 && usable "$(command -v "$c")"; then
            CANDIDATE="$(command -v "$c")"; break
        fi
    done
fi

if [ -z "$CANDIDATE" ] || ! usable "$CANDIDATE"; then
    warn "未找到 3.9-3.13 的 Python。"
    echo "    macOS : brew install python@3.11"
    echo "    Ubuntu: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.11-venv"
    exit 1
fi
ok "使用 $CANDIDATE"
ok "版本 $("$CANDIDATE" -c 'import sys;print(sys.version.split()[0])')"

# ------------------------------------------------------------------ 2. venv
if [ "$RECREATE" = "1" ] && [ -d "$VENV" ]; then
    step "重建 venv（删除旧的 .venv）"
    rm -rf -- "$VENV"
fi
if [ ! -x "$PY" ]; then
    step "创建独立虚拟环境"
    "$CANDIDATE" -m venv "$VENV"
    ok "已创建 .venv"
else
    step "复用已有 .venv"
    ok "$("$PY" -V 2>&1)"
fi

# -------------------------------------------------------------- 3. 基础工具
step "升级 pip / setuptools / wheel"
"$PY" -m pip install --upgrade pip setuptools wheel --disable-pip-version-check --quiet
ok "$("$PY" -m pip --version)"

# ------------------------------------------------------------------- 4. 依赖
step "安装项目依赖（含 dev / journal 扩展）"
echo "    pandas + akshare + openpyxl + pytest，首次约 100 MB，请耐心等待…"
( cd "$ROOT" && "$PY" -m pip install -e ".[dev,journal]" --disable-pip-version-check )
ok "依赖安装完成"

# ------------------------------------------------------------------- 5. 自检
step "环境自检"
set +e
( cd "$ROOT" && "$PY" -m limitup doctor )
CODE=$?
set -e

echo
if [ "$CODE" -eq 0 ]; then
    printf "${c_green}bootstrap 成功。${c_off}\n\n"
    echo "下一步："
    echo "  .venv/bin/python -m limitup journal"
    echo "  .venv/bin/python -m limitup pools"
    echo "  .venv/bin/python -m pytest"
    echo
    echo "想少打字就先激活： source .venv/bin/activate"
else
    warn "doctor 返回 $CODE，请查看上面的输出。"
    exit "$CODE"
fi
