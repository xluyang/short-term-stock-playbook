#Requires -Version 5.1
<#
.SYNOPSIS
    在本项目内建立独立虚拟环境并安装全部依赖（Windows / PowerShell）。

.DESCRIPTION
    所有依赖都落在 <repo>\.venv，不读写任何外部虚拟环境或全局 site-packages。
    重复执行是安全的：已存在的 venv 会被复用，pip 只补齐缺失包。

.PARAMETER Python
    指定基础解释器路径。省略时自动探测 3.11 -> 3.12 -> 3.10 -> 3.13 -> PATH 上的 python。

.PARAMETER Recreate
    删掉已有 .venv 重建（仅删除 .venv，不动其它任何目录）。

.PARAMETER SkipInstall
    只建 venv 与升级 pip，不安装项目依赖。

.EXAMPLE
    .\scripts\bootstrap.ps1

.EXAMPLE
    .\scripts\bootstrap.ps1 -Recreate
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Recreate,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$Py   = Join-Path $Venv 'Scripts\python.exe'

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "    $Text" -ForegroundColor DarkGray }
function Write-Warn2([string]$Text){ Write-Host "!!  $Text" -ForegroundColor Yellow }

Write-Host ''
Write-Host 'short-term-stock-playbook bootstrap' -ForegroundColor Green
Write-Host ("  repo : {0}" -f $Root)
Write-Host ("  venv : {0}" -f $Venv)
Write-Host ''

# ---------------------------------------------------------------- 1. 解释器
Write-Step '定位 Python 3.9-3.13'
$minMinor = 9
$maxMinor = 13

function Test-Usable([string]$exe) {
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    $raw = & $exe -c "import sys;print('%d %d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $false }
    $parts = ($raw -split '\s+')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    return ($major -eq 3 -and $minor -ge $minMinor -and $minor -le $maxMinor)
}

$found = $null
if ($Python) {
    if (-not (Test-Usable $Python)) { throw "指定的解释器不可用或版本不在 3.9-3.13：$Python" }
    $found = $Python
} else {
    $probe = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        'C:\Python311\python.exe',
        'C:\Python312\python.exe'
    )
    foreach ($p in $probe) {
        if (Test-Usable $p) { $found = $p; break }
    }
    if (-not $found) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd -and (Test-Usable $cmd.Source)) { $found = $cmd.Source }
    }
}
if (-not $found) {
    Write-Warn2 '未找到 3.9-3.13 的 Python。'
    Write-Host '    安装方式： winget install -e --id Python.Python.3.11 --scope user'
    Write-Host '    或到 https://www.python.org/downloads/ 手动安装后重跑本脚本。'
    exit 1
}
Write-Ok "使用 $found"
$ver = & $found -c "import sys;print(sys.version.split()[0])"
Write-Ok "版本 $ver"

# ------------------------------------------------------------------- 2. venv
if ($Recreate -and (Test-Path -LiteralPath $Venv)) {
    Write-Step '重建 venv（删除旧的 .venv）'
    Remove-Item -LiteralPath $Venv -Recurse -Force -Confirm:$false
}
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Step '创建独立虚拟环境'
    & $found -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv 失败（退出码 $LASTEXITCODE）" }
    Write-Ok '已创建 .venv'
} else {
    Write-Step '复用已有 .venv'
    Write-Ok (& $Py -V)
}

# ------------------------------------------------------------- 3. 基础工具
Write-Step '升级 pip / setuptools / wheel'
& $Py -m pip install --upgrade pip setuptools wheel --disable-pip-version-check --quiet
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败（退出码 $LASTEXITCODE）" }
Write-Ok (& $Py -m pip --version)

# ------------------------------------------------------------------ 4. 依赖
if (-not $SkipInstall) {
    Write-Step '安装项目依赖（含 dev / journal 扩展）'
    Write-Host '    pandas + akshare + openpyxl + pytest，首次约 100 MB，请耐心等待…'
    Push-Location $Root
    try {
        & $Py -m pip install -e ".[dev,journal]" --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw "依赖安装失败（退出码 $LASTEXITCODE）" }
    } finally {
        Pop-Location
    }
    Write-Ok '依赖安装完成'
}

# ------------------------------------------------------------------ 5. 自检
Write-Step '环境自检'
Push-Location $Root
try {
    & $Py -m short_term_stock_playbook doctor
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ''
if ($code -eq 0) {
    Write-Host 'bootstrap 成功。' -ForegroundColor Green
    Write-Host ''
    Write-Host '下一步：'
    Write-Host '  .\.venv\Scripts\python.exe -m short_term_stock_playbook journal'
    Write-Host '  .\.venv\Scripts\python.exe -m short_term_stock_playbook pools'
    Write-Host '  .\.venv\Scripts\python.exe -m pytest'
    Write-Host ''
    Write-Host '想少打字就先激活： .\.venv\Scripts\Activate.ps1'
} else {
    Write-Warn2 "doctor 返回 $code，请查看上面的输出。"
    exit $code
}
