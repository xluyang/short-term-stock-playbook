# short-term-stock-playbook

<p align="center">
  <a href="https://www.youtube.com/watch?v=ChQ-6tzv3-4" title="点击播放主题视频">
    <img src="https://img.youtube.com/vi/ChQ-6tzv3-4/maxresdefault.jpg" alt="short-term-stock-playbook 主题视频" width="720">
  </a>
  <br>
  ▶️ <b>主题视频</b>：点击封面直接播放（<a href="https://www.youtube.com/watch?v=ChQ-6tzv3-4">YouTube</a>）
</p>

> **A 股短线打板打法手册**：一套可执行的涨停接力 playbook —— 规则文档 → 环境判定 → 方向承接 → 个股打分 → 交易打卡，五段闭环。
> 规则来自一段直播口播的结构化还原，工程上补齐了仓位、过滤、风控与验证。

[![CI](https://github.com/xluyang/short-term-stock-playbook/actions/workflows/ci.yml/badge.svg)](https://github.com/xluyang/short-term-stock-playbook/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%20%7C%203.11%20%7C%203.13-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![status](https://img.shields.io/badge/status-alpha-orange)
![data](https://img.shields.io/badge/data-akshare-9cf)

> ⚠️ **免责声明**：本项目仅供个人研究与交易记录，**不构成投资建议**，不提供下单接口。数据来自第三方公开接口，准确性不作保证。打板为高风险交易方式，亏损自负。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [快速开始](#快速开始)
- [三大部分](#三大部分)
- [打卡表怎么用](#打卡表怎么用)
- [命令参考](#命令参考)
- [模型参数](#模型参数)
- [项目结构](#项目结构)
- [数据说明](#数据说明)
- [验证方法](#验证方法)
- [已知限制](#已知限制)
- [路线图](#路线图)
- [关于名字](#关于名字)
- [许可证](#许可证)

---

## 它解决什么问题

短线打板的核心不是"选到涨停股"，而是**在正确的日子、正确的方向、正确的时间点，只做高确定性的那一个板**。散户亏钱通常不是选错票，而是：

1. 环境不对（弱势区照样满仓）→ 池 A 用来解决；
2. 方向不对（做了没人接力的板块）→ 池 B 用来解决；
3. 时间不对（早盘追高被埋）→ 时间窗用来解决；
4. 没有记录（不知道自己的封板率、胜率、盈亏比）→ 打卡表用来解决。

本项目把这四件事变成可执行的清单与可统计的表格。

## 快速开始

本项目**完全自包含**：解释器环境 `.venv` 建在仓库根目录，依赖只装进 `.venv`，不读取、不修改任何外部虚拟环境或全局 site-packages。

### 一键脚本（推荐）

```bash
git clone https://github.com/xluyang/short-term-stock-playbook.git
cd short-term-stock-playbook

# Windows
.\scripts\bootstrap.ps1

# macOS / Linux
./scripts/bootstrap.sh
```

脚本会依次：定位 3.9–3.13 的 Python → 建 `.venv` → 升级 pip → `pip install -e ".[dev,journal]"` → 跑 `short-term-stock-playbook doctor` 自检。重复执行安全（复用已有 `.venv`），`-Recreate` / `--recreate` 可重建。

> Windows 若提示「禁止运行脚本」，改用：
> `powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1`
> macOS / Linux 首次可能需要 `chmod +x scripts/bootstrap.sh`。

### 手动等价操作

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev,journal]"    # akshare / pandas / openpyxl / pytest / ruff

short-term-stock-playbook doctor                     # 环境自检（离线）
short-term-stock-playbook journal                    # 生成打卡表 -> output/journal_YYYYMMDD.xlsx
short-term-stock-playbook pools                      # 构建当日三层标的池（需联网取数）
```

> 不想激活也行，直接用 `.\.venv\Scripts\python.exe -m short_term_stock_playbook doctor`（Windows）或 `.venv/bin/python -m short_term_stock_playbook doctor`（macOS/Linux）。

### 依赖清单

全部声明在 [`pyproject.toml`](pyproject.toml)，没有隐藏依赖：

| 依赖 | 版本 | 用途 |
|---|---|---|
| `pandas` | ≥2.0 | 数据处理 |
| `akshare` | ≥1.14 | 行情与涨停池数据（唯一数据源） |
| `openpyxl` | ≥3.1 | `journal` 扩展：生成 xlsx |
| `pytest` / `ruff` | — | `dev` 扩展：测试与检查 |

只想要筛选不生成 Excel？`pip install -e .` 即可，省掉 openpyxl。

## 三大部分

### 1. 规则文档 —— [`docs/model.md`](docs/model.md)

完整模型：原文规则 → 可操作定义的映射表、三层池、9 条硬性过滤、打分卡、执行时间轴、风控阈值、验证方案、已知缺陷。

### 2. 打卡表 —— `short-term-stock-playbook journal`

`templates/journal_template.xlsx` 是预先生成好的空模板（21 KB），直接双击就能填；想要一份新的执行 `short-term-stock-playbook journal --out 任意路径.xlsx`。

Excel 三页：

| 页 | 内容 |
|---|---|
| 打卡 | 20 列 × 120 行，总分/隔日溢价/账户贡献为公式，`是否封住` 带下拉校验 |
| 统计 | 总笔数、封板率、胜率、盈亏比、累计贡献、平均得分，**全部公式自动更新** |
| 说明 | 每列口径 + 打分规则 + 免责声明 |

### 3. 筛选脚本 —— [`src/short_term_stock_playbook/`](src/short_term_stock_playbook/)

| 模块 | 职责 |
|---|---|
| `data.py` | 唯一接触 akshare 的地方；列名归一化 + 本地 csv 缓存 |
| `pools.py` | 池 A/B/C 构建（纯函数，可单测） |
| `score.py` | 打分卡（纯函数，零依赖） |
| `journal.py` | 打卡表生成器（openpyxl） |
| `ths.py` / `ths_store.py` | 三层池 → 同花顺自选股分组同步（写本机文件，默认 dry-run） |
| `web.py` | 三层池 → 本地 HTML 看板（个股可点击跳转网页版行情） |
| `cli.py` | `doctor` / `pools` / `web` / `screen` / `journal` / `ths` |
| `report.py` | 中文对齐的控制台表格与 CSV 导出 |

### 4. 同花顺同步 —— `short-term-stock-playbook ths`

把当日三层池写进本机同花顺的三个自选股分组（`TOP5` / `池B承接` / `池C连板`），覆盖式更新、不每天建新组。默认 dry-run 只生成 `output/ths_manifest.json` 清单；`--apply` 才真正写文件。

- **写前自动备份**：每个被改文件先拷一份带时间戳的副本到 `同花顺用户目录/backup/`，错了可回滚。
- **不碰无关数据**：加密段（条件选股）、其它分组、自选股总表（`SelfStockInfo.json`）一律不动；分组名复用已存在的分组 ID，查不到才派生新 ID。
- **必须先关同花顺**：同花顺运行时把这些文件留在内存里，退出时会覆盖；请先退出同花顺再 `--apply`。
- 定位规则：扫描 `C:`/`D:` 下 `*同花顺*` 目录，找含 `hexin.exe` 的安装目录，再选 `stockblock.ini` 修改时间最新的用户数据目录（排除访客目录）。

### 5. 本地面板 —— `short-term-stock-playbook web`

把三层池渲染成一份**单文件 HTML**（`output/playbook_YYYYMMDD.html`，约 60 KB，零外部依赖），
双击就能看，也可以直接发群里 / 传到手机。

- **分组即分区**：TOP5 / 池B承接 / 池C连板 各一块；池 C 按连板高度降序，带 `C2` / `C1` 标签。
- **点击个股跳到网页版行情**：每张卡片都是一个新窗口链接，默认指向同花顺个股页
  （`stockpage.10jqka.com.cn`），页面顶部可一键切到东方财富或雪球 —— 切换只改 href，不刷新。
- **`/` 直接搜**：输入代码或名称实时过滤，`Esc` 清空。池 C 常有 90+ 只，靠这个找票。
- **环境提示内置**：S 值、单票仓位上限、数据日期都在页头；任意一层为空时顶部亮黄条提醒「当日不做」。
- `--open` 生成后直接用默认浏览器打开；`ths` 命令默认也会顺带生成这份看板（`--no-html` 关闭）。

## 打卡表怎么用

1. 每笔交易填一行，**只填白底列**：S值、方向分、资质分、时间窗分、形态分、买入价、是否封住、次日开盘价、仓位。
2. 灰列是公式，别覆盖：
   - `总分 = S值/5×30 + 方向分 + 资质分 + 时间窗分 + 形态分`
   - `隔日溢价 = (次日开盘价 − 买入价) / 买入价`
   - `账户贡献 = 隔日溢价 × 仓位`
3. 统计页不用管，随填随算。
4. **总分 < 70 却下了单**，在备注写「违规」——统计页会自动算违规笔数，这是复盘最有价值的一列。

各分项口径见打卡表「说明」页，或 [`docs/model.md`](docs/model.md) 第 6 节。

## 命令参考

| 命令 | 作用 |
|---|---|
| `short-term-stock-playbook doctor` | Python / pandas / akshare 版本、缓存目录、当前模型参数摘要 |
| `short-term-stock-playbook pools [--date YYYY-MM-DD] [--history-days 90] [--offline] [--source auto|em|sina]` | 打印池 A / 池 B / 池 C |
| `short-term-stock-playbook web [--date YYYY-MM-DD] [--out 路径] [--link ths|em|xueqiu] [--open] [--offline]` | 生成可点击的本地 HTML 看板 |
| `short-term-stock-playbook screen [--minutes 25] [--form pullback] [--offline] [--source auto|em|sina]` | 当日涨停股打分（触板时间与形态需人工确认） |
| `short-term-stock-playbook journal [--out 路径] [--rows 120]` | 生成打卡表 |
| `short-term-stock-playbook ths [--offline] [--source auto|em|sina] [--apply] [--no-html]` | 同步三层池到同花顺自选股分组（默认 dry-run；`--apply` 写本机文件，需先关闭同花顺；同时生成 HTML 看板） |

`--offline`：完全不发网络请求，只读 `cache/`。被东财限流时靠它继续工作。

## 模型参数

全部集中在 [`src/short_term_stock_playbook/config.py`](src/short_term_stock_playbook/config.py)，回测调参只改这一处：

| 参数 | 默认 | 含义 |
|---|---|---|
| `TOP_N` | 5 | 池 A 取成交额前 N |
| `MIN_S` | 3 | S 低于此值空仓 |
| `S_POSITION` | 5→30% / 4→22% / 3→12% | S 值对应仓位上限 |
| `HANDOFF_MIN_AMOUNT` | 10 亿 | 池 B 首板成交额门槛 |
| `HIST_WINDOW_2 / 4` | 10 / 90 日 | 池 C 连板历史窗口 |
| `MIN_AMOUNT` | 5 亿 | 个股成交额下限 |
| `EXEC_START / END` | 20 / 60 分钟 | 9:50–10:30 执行窗口 |
| `MIN_SCORE` | 70 | 下单达标线 |

## 项目结构

```
short-term-stock-playbook/
├─ docs/model.md              模型规格（核心文档）
├─ src/short_term_stock_playbook/               筛选工具包
│  ├─ data.py                 唯一接触 akshare 的层
│  ├─ pools.py / score.py     纯函数：建池、打分
│  ├─ journal.py / report.py  输出：xlsx 打卡表、终端表格
│  ├─ web.py                  输出：本地 HTML 看板（个股可点击跳转）
│  └─ cli.py / config.py      命令入口、全局阈值
├─ tests/                     单测（零联网，不依赖 akshare）
├─ templates/                 打卡表模板（由 short-term-stock-playbook journal 生成）
├─ scripts/
│  ├─ bootstrap.ps1           Windows 一键装环境（只用项目内 .venv）
│  └─ bootstrap.sh            macOS / Linux 同上
├─ output/                    生成物（git 忽略）
├─ .venv/                     项目自带解释器环境（git 忽略）
└─ pyproject.toml             依赖与打包的唯一声明处
```

### 环境隔离约定

- 运行期只认 `<repo>/.venv`，**不 fallback 到系统 Python、不读取其它项目的 venv**。
- 依赖版本全部由 `pyproject.toml` 钉住范围，换个机器 `bootstrap` 一遍结果一致。
- 环境坏了直接 `bootstrap.ps1 -Recreate` / `bootstrap.sh --recreate`，重建不动源码与数据。
- `cache/` 与 `output/` 是运行期目录，删掉不影响正确性，只会重新拉数。

## 数据说明

- 数据源：**akshare**（免费公开接口），字段映射见 `data.py` 的 `SPOT_MAP` / `ZT_MAP` / `PREV_ZT_MAP`。
- **今日涨停池与昨日涨停池是两套 schema**：`stock_zt_pool_em` 有封板资金/炸板次数，`stock_zt_pool_previous_em` 只有「昨日连板数 / 昨日封板时间」。所以映射表分成两张。
- 历史涨停池会落 `cache/*.csv` 并在下次直接复用（池 C 要回看 90 个交易日，没缓存每次要打 90 次请求）；**当日数据不在缓存里读**，因为盘中会变。
- 缓存往返会把股票代码的前导零吃掉（`000525` → `525`），已在读取时强制按字符串处理。
- akshare 版本升级可能改列名 → 报错信息会打印「必需列」与「实际列」，照着改映射表即可。
- 本项目**不存储、不分发**任何行情数据；不包含个股推荐。

### 被东方财富限流了怎么办

`stock_zh_a_spot_em` 一次要翻几十页拉全市场 5000+ 只票，是限流的头号触发点。**默认 `--source auto` 会在东财限流时自动回退到新浪源**（`stock_zh_a_spot`，字段更少但服务器不同、不受东财限流）；想直接走新浪就 `--source sina`。症状是：

```
拉取行情快照失败：东方财富 push2 行情服务器断开了连接，通常是短时间内请求过多…
```

处理顺序（**不要边等边重试，会延长限流**）：

1. **有当日缓存就离线跑**：`short-term-stock-playbook pools --offline`，一个请求都不发；
2. **没缓存就等**：首次限流一般 5 分钟恢复，反复触发可能 40 分钟以上；
3. **改成一天只拉一次**：`spot` 在 15:05 之后会自动复用当日缓存，收盘后跑一遍即可，不用反复跑。

已内置的减负措施：

| 措施 | 效果 |
|---|---|
| 15:05 后复用当日 spot 缓存 | 全天只需 1 次全市场请求 |
| 历史涨停池按日缓存 | 池 C 的 90 天回看第二次起 0 请求 |
| 交易日历缓存 24 小时 | 只从新浪拉一次 |
| `--offline` 全局开关 | 断网 / 限流时完全离线 |

## 验证方法

策略是否有效，只看四个数（打卡表统计页自动算）：

| 指标 | 目标 |
|---|---|
| 封板率 | > 65% |
| 胜率 | > 55% |
| 盈亏比 | > 1.5 |
| 平均隔日溢价 | > 2% |

**样本门槛**：≥ 100 笔、跨 ≥ 3 个月、包含至少一段退潮期。

**必须有对照组**：同样的票、同样的日期，随机在 9:50 后买入。若两组收益无差异，说明规则没有 alpha。

**过拟合检查**：阈值（S≥3、10 亿、10 日、90 日）各上下浮动 20% 重跑，结论应保持同向。

## 已知限制

- `screen` 是**骨架**：首次触板时间与分时形态需要分时数据（`stock_zh_a_hist_min_em`）或人工判断，尚未自动接入。
- **池 A 的时点由运行时刻决定**：`spot()` 拿的是「调用瞬间」的全市场快照。**开盘前跑 → 数据是昨日的**（这才是模型要的、无未来函数）；**收盘后跑 → 数据是今日的**（适合复盘、准备明天的池）。同一条命令，跑的时间不同含义不同。
- 板块归属（池 B 的方向聚合）需要额外的成分股接口，当前只返回个股；`sector` 字段已带出，但尚未做聚合。
- 无回测引擎：历史回放建议把 `pools` / `score` 当纯函数，自己写循环。
- 打板滑点常 > 1%，而策略赚的是 ~2% 的隔日溢价，**执行速度决定生死**。
- 同花顺同步是**逆向本机文件格式**实现的（`stockblock.ini` + `custom_block/*.json`），不同版本/渠道可能布局不同；跑 `--apply` 前先 dry-run 看一眼清单，写入后在同花顺里确认分组正确。
- **同花顺同步只改本地文件，不会推到手机端**：同花顺的云同步是带版本号的私有协议（`SelfStock` 平铺列表 / `CustomBlock` 分组），只在**通过它界面改动**时才上传并推送手机；`--apply` 直接写文件不触发上传。要让手机同步，写完 `--apply` 后需在电脑版同花顺里手动做一次界面改动（如任意分组里加删一只票），逼它上传当前状态。

## 路线图

- [x] 三层池构建 + 打分卡 + 打卡表
- [x] 同步三层池到同花顺自选股分组（`ths --apply`）
- [x] 三层池 → 本地 HTML 看板，个股点击跳转网页版行情（`web`）
- [ ] 接入分时接口，自动计算首次触板时间
- [ ] 板块成分与涨停家数聚合
- [ ] 历史回测引擎（事件驱动，含滑点模型）
- [ ] 情绪指标（炸板率、连板高度、跌停家数）作为全局开关
- [ ] 打卡表自动读取成交记录（券商导出 csv）

## 关于名字

`short-term stock` 指 A 股短线交易（本项目聚焦涨停接力的短周期打法）；`playbook` 指一支队伍的**战术手册**。

打板亏钱很少是因为「找不到涨停的票」，多数是因为**没有一套必须遵守的打法**：什么环境下才做、做哪个方向、几点下单、错了怎么退、事后怎么复盘。本项目把这几件事写成了一本可执行的 playbook —— 规则写死在文档里、阈值写死在 `config.py`、执行痕迹落在打卡表里。

所以它不是一个选股器（screener），而是一本**要照着做的**手册。

## 许可证

[MIT](LICENSE) © 2026 max_h

> 模型规则来自公开直播内容的结构化整理，仅作个人研究记录；如涉及版权问题请联系删除。
