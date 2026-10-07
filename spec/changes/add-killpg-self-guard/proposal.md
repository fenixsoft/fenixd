# Proposal: add-killpg-self-guard

## Why

2026-10-07 全量回归击杀死循环取证实锤**两起同构事故**：测试替身 proc 的 pid 怪值使产品清场代码的进程组击杀命中**调用者自身所在进程组**，把整个测试套件/批回归团灭（-9 与 -15 两个信号变体；ftrace `signal_generate` 取证发送者=pytest 主进程自身）。逐个修替身是打地鼠——`test_knowledge_backfill.py` pid=0 修掉后，其它替身（如 `test_codefix_digest_metrics.py` 仍存 `self.pid = 0`）随时可能在新负载/时序下引爆同类团灭。需要在产品清场侧加**统一自保护守卫**，一次性根治所有替身 pid 怪值变体（含未来新增的）。

## What Changes

- `core/proc_utils.py` 新增统一守卫助手：执行 `os.killpg` 前校验**目标进程组不得是调用者自身所在进程组**（`os.getpgid(0)`）；命中即拒绝执行并记 WARNING 日志（含调用点标识与目标 pgid）。
- 兼容两种既有入参形态：`getpgid` 型（传 proc.pid，先 `os.getpgid(pid)` 解析——`core/regression.py _kill_process_group` 等）与**组长直传型**（传独立成组组长的 pid，如 `core/agent_runner/maintenance_runs.py _kill_ocr_process_group`、`core/agent_runner/liveness.py`）；解析后的 pgid 进入同一守卫校验。
- 各清场点收口到守卫助手：**SIGTERM → 宽限等待 → SIGKILL 补刀的既有序列语义逐位不变**，仅替换真正执行 killpg 的最后一跳。
- **fail-closed 静默语义**：守卫拒绝时清场函数按既有「组已不存在（ProcessLookupError/OSError）」路径静默返回，MUST NOT 抛异常改变调用方控制流。
- 测试替身的存量怪值（`tests/test_codefix_digest_metrics.py` 的 `self.pid = 0`）随本 SPEC 一并修正（与 `test_knowledge_backfill.py` 先例同款：改为不可达 pid），替身修复与守卫互为冗余防御。

## Capabilities

### New Capabilities

- `killpg-self-guard`: 进程清场击杀的自保护守卫——任何清场路径不得击杀调用者自身所在进程组；目标组=自身组时拒绝、告警、按组不存在静默降级。

### Modified Capabilities

（无——既有各车道 SPEC 声明的是「杀整树防孤儿」语义，守卫不改变该语义，仅排除自伤误命中）

## Impact

- **代码面**：`core/proc_utils.py`（守卫助手 new helper）；清场收口 `core/regression.py`、`core/agent_runner/liveness.py`、`core/agent_runner/maintenance_runs.py`、`core/v2_dev_server.py`、`core/adjudication_narrative.py`、`core/knowledge_backfill.py`、`core/dashboard/ocr_status.py`、`core/serving_registry.py`（以 grep `os.killpg` 全量盘点为准，仅收口「清场击杀」语义点；`os.kill` 单 pid 击杀不在范围内）。
- **风险**：守卫校验引入的额外 `os.getpgid(0)` syscall 在清场路径（低频）开销可忽略；既有「真孤儿组」清理语义不受影响（孤儿组 pgid ≠ 调用者自身组）。
- **验收口径**：守卫落地后，`tests/` 全量在替身怪值存在的前提下不再出现「套件被自身进程组击杀」（ftrace `signal_generate` 发送者=pytest 自身、接收者含宿主组的形态）。
