# Proposal: fix-windows-review-longtail

## Why

Windows 真机部署第三轮评审（同机二测，docs/《fenixd-install-md-二轮评审.md》C 节）给出两条已核实的产品层长尾缺陷，用户定调立项处理：

1. **C3 — skill 命令口径**：`skills/*/SKILL.md` 通篇以 `python3` 书写可复制命令（8 个 skill 共 38 处），Windows 部署者/agent 每次都要自行换算成 `py -3`，漏换即 `python3` 不存在（Windows 无 python3 别名）。
2. **C4 — install_unit stderr 噪音**：`core/platform/win32.py` `install_unit` 的**首装路径**（服务未装 → state=None → 正常安装决策）也发 `_logger.warning("状态查询无响应…")`，读起来像报错；且 win32 平台 logger 的中文消息写 stderr 在 GBK/cp1252 控制台可触发 `UnicodeEncodeError` traceback 混入捕获流（E2E 实测命中，评审者误判为故障）。

两项都是部署可观测性/易用性缺陷，不改变任何功能契约；趁部署评审热度立即收敛，避免下一轮部署评审重复报告。

## What Changes

- **C3（文档口径）**：为 8 个 `skills/*/SKILL.md` 引入统一的「Windows 命令换算」校准注记（`python3` ⇒ Windows 一律 `py -3`），并在每个 skill 的高频可复制命令处行内双写关键形态；纯文档改动，不改任何代码与 skill 触发语义。
- **C4（产品日志路径）**：`install_unit` 首装路径的状态查询告警降级（正常「未安装」走 debug 级/静默，仅在拿到 sc 瞬时失败证据时保留 warning）；win32 平台日志输出编码安全化（stderr 写入 errors=replace，杜绝 GBK 控制台下 UnicodeEncodeError traceback 混入）。**不改变** `install_unit` 返回 JSON 形状、服务安装行为与 Linux 后端任何代码。

### v0.1.0 部署实录扩展（2026-11-15 用户真机全量部署实测，附件《fenixd-v0.1.0-部署实录与改进建议.md》）

- **C5（subprocess 输出解码——C4 噪音的真实根因修正）**：`core/platform/win32.py` 全部 `subprocess` `capture_output` 处按 UTF-8 解码 sc.exe/nssm 输出；GBK 控制台+提权 PS5.1 下 sc 输出含 GBK 双字节（首字节 0xb0 等）→ `UnicodeDecodeError` 读线程崩 → 被归一成「状态查询无响应」假告警（**确定性发生**，非瞬态）。修法：`subprocess.run(..., text=True, encoding="utf-8", errors="replace")`。
- **C6（fenix-init 原子性/preflight）**：骨架全读面（`.fenix/config.template.yaml`、`FENIX_LINKS`、`AGENT_LINKS`、`templates/`）在**建目录之前**前置校验，任一缺失即失败退出（exit 2 + 缺失明细）；v0.1.0 制品缺模板时 fenix-init 在 mkdir 之后才崩，留下半成品骨架。`render_config` 失败时清理已建目录（原子性承诺）。
- **C7（fenix-init `--version`）**：提供 `--version`（读包根 VERSION），部署验证门可机器判读。
- **C8（骨架清单悬空引用）**：`FENIX_LINKS` 含 `__init__.py` 但源码根并不存在该文件（v0.1.0 与源码形态都缺）→ 从清单移除，不在制品中虚构文件。
- **C9（install.ps1 完整性硬失败）**：部署面/模板缺失从「WARN + exit 0 静默降级」改为**硬失败 exit 非 0**（与打包侧 21 项断言双保险——打包侧已随本轮落地 `scripts/package.sh` 完整性断言）。
- 文档与流水线项（不占 SPEC 任务，已随本轮直接落地）：install.md §3A sha256 / §4b `--help` 与完整性前哨 / §10 镜像代理与 claude -p 挂起两行 / §8 UAC 批量提权注记 / §9.0 PS 冒烟等价命令；`scripts/package.sh` 打包面重写 + 断言；`.github/workflows/release.yml` 三段式（release → pack-smoke → publish）。

## Capabilities

### New Capabilities

（无——两项均为既有能力的缺陷修复，不引入新行为面）

### Modified Capabilities

- `windows-native-support`：安装链可观测性要求收紧——首装路径零噪音（正常路径不发 warning 级信号）、平台日志输出编码安全（GBK/cp1252 控制台下无 traceback 混入）；skill 部署文档口径双平台化。既有能力 spec 见 `spec/changes/windows-native-support/specs/`（活跃变更）。

## Impact

- 代码：`core/platform/win32.py`（install_unit 告警分级 + subprocess 解码加固 + logger stderr 编码安全）；`fenix-init`（仓库根脚本；preflight 前置 + --version + FENIX_LINKS 去 `__init__.py`）；`install.ps1`（完整性硬失败）；`tests/test_platform_pal.py`（Linux 可跑纯逻辑层新增覆盖）。
- 文档：`skills/{fenix-approve,fenix-archive,fenix-dashboard,fenix-new,fenix-process,fenix-prototype,fenix-setup,fenix-status}/SKILL.md`。
- 风险面：win32 改动仅日志、subprocess 解码与告警分级路径，不触进程 API 契约（Popen 句柄/ctypes 原型未动）——按知识页「过机复验铁则」的 API 面口径，本轮以 Linux 契约测试收口 + 设计声明豁免过机（下次过机窗口顺带复验）。
- 兼容性：无 breaking；Linux 行为逐位不变（Linux 零变化硬约束）。
