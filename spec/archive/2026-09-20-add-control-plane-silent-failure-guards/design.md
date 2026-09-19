# 控制平面静默失效防线 — 设计

## Context

2026-09-14 `evo-item-retention-doc-tracking` 事故已定位为三层叠加缺陷（详见 `proposal.md` §Why）。本设计回答"怎么修、为什么这么修"。约束：

- **零生产行为回归**：守卫类改动（防线一/二）是纯新增测试，不触生产路径；升级类改动（防线三/四）须保持既有信号语义与节流不变。
- **保守起步**：静态守卫易误报，宁可少判不可误判——只用"方法名唯一 + 无变长参数"这类强约束判定。
- **右关联设计不可破坏**：`admin_monitor` 的处置记录先落盘（永不重抛），升级告警自身失败只能记日志。

## Goals / Non-Goals

**Goals**
- 把"CI 全绿但代码是坏的"这一类静默盲区封死在提交时（防线一/三）。
- 把"控制平面失效被静默降级"改为可升级可见（防线二/三）。
- 把"状态悬置却无人驱动"从分钟级可发现（防线四），而非 160 分钟后才由 `stuck` 兜底。

**Non-Goals**
- 不改 `stuck` 既有阈值与节流语义。
- 不改 `blocked` 复位路径语义（`resolve_env_blocked_reset_path`）。
- 不引入 mypy/pyright 等重型静态类型检查（环境未装、依赖面大）。
- 不重构 `except Exception` 全局（419 处）——只治理控制平面复位路径这一处。

## Decisions

### D1 静态守卫用 AST 扫描 + 单元测试，而非运行时断言或 pyright

**选择**：新增 `tests/test_callsite_arity_guard.py`、`tests/test_fake_double_fidelity.py`，用 `ast` 解析源码做静态断言。

**理由**：
- pyright/mypy 未安装、且需要全量类型标注才能生效；本仓库无类型检查配置，引入成本大、噪音多。
- 运行时断言（如在 `handle_event` 里 `assert len(...)`）无法捕获"调用点写错"——它只会在真的跑到那一步才炸，正是本事故的形态。
- AST 扫描零依赖、确定性、可在 CI 的 `pytest tests/` 里跑，且**不依赖被测代码真的被执行**（本事故恰恰是那条路径从未被执行）。

**已实测**：落地时对现网 `core/` 跑 arity 扫描，白名单外违规 = 0（仅 `logger.warning(f-string)` 等同名误报需白名单）；对 `tests/` 跑替身保真扫描，收紧 5 处后违规 = 0。即**纯加地板、零既有欠债**。

**备选**：`unittest.mock.create_autospec` 替代手写替身——更强（自动校验签名），但要改写既有 5 处替身且限制 MagicMock 用法；本设计保留其为后续强化方向（见 Open Questions），当前先用"扫描既有替身签名"的保守版。

### D2 守卫规则用"方法名唯一"作为同契约判据

**选择**：只有当方法名在 `core/` 中**唯一签名**、且该签名无 `*args`/`**kwargs`、非 dunder、不在宽泛名黑名单时，才参与比对。

**理由**：跨类同名方法（`get`/`items`/`warning`…）语义不同，若不加约束，"同名即同契约"不成立会大量误报。方法名唯一时，合理假设"同名即同一 seam"。

**备选**：按类型推断（数据流分析）——过重，不划算。

### D3 编程错误白名单用 `(TypeError, AttributeError, NameError)`

**选择**：`_reset_env_blocked_after_disposition` 前置 `except (TypeError, AttributeError, NameError)` → 升级；其余走原 `except Exception` → WARNING。

**理由**：这三类是 Python 里**代码缺陷**的典型签名（实参不符 / 属性缺失 / 未定义名），重试无意义。其余异常（`OSError`/`subprocess.CalledProcessError`/网络）多为运维失败，重试或人工可能有救，保持 WARNING 降噪。

**备选**：全部异常都升级——会淹没在运维噪音里，违背"升级即可见"的初衷。

### D4 升级告警携带"调用点"

**选择**：`traceback.extract_tb(exc.__traceback__)` 取 `core/` 内最深栈帧，写 `文件:行 (函数名)` 进 evidence。

**理由**：复现本事故需要读源码/日志才知道坏在哪行；把调用点直接写进告警，工程侧无需复现即可定位。

### D5 `orphaned_state` 三条件 + 短阈值

**选择**：`status ∈ {implementing, testing}` 且 ①无活动 run 文件（mtime 超宽限）②无存活 agent 子进程 ③无待派发（backoff 未到期 / `_cancelled_hold` / `start_after` 未到）→ 信号；阈值默认 10–15 分钟（独立配置键，缺省合理）。

**理由**：
- 只看状态时间戳会误杀长 run（实现/验证可达数十分钟）——必须叠加"无活动 run + 无进程"双兜底。
- 复用 `event_bus` 现有的 `_pgrep_live_worktree`/`_latest_impl_run_file`/`_run_file_recent` 逻辑思路（admin_monitor 侧已有 `_has_recent_progress`），不重复造。
- 阈值短于 `stuck`（160 分钟）是核心价值：本事故悬置 1h12m，若早 10 分钟发现可省下全部空转。

**备选**：直接改 `stuck` 阈值——会影响既有多处语义（`pm_engine.check_blockers` 同源），风险大；新增独立信号更安全。

### D6 `testing` 态恢复出口补在 `event_bus._recover_one`

**选择**：`_recover_one` 现只覆盖 `drafted/reviewing/implemented/ready/bug-found/verified`，补 `testing` 无驱动分支（发现则触发重派或联动 `orphaned_state`）。

**理由**：`testing` 在 `INTERRUPTED_STATES` 中，daemon 重启是可恢复的（回退 `implemented`）；但**运行期**没有出口——这正是"悬置必须等重启"的结构根因。

## Risks / Trade-offs

- **[orphaned_state 误报]** 正常长 run 被误判无驱动 → **缓解**：三条件与（无活动 run + 无存活进程 + 无待派发）必须同时成立；长 run 一定有 mtime 新鲜的 run 文件或存活进程。
- **[静态守卫误报]** 同名方法误判 → **缓解**：唯一签名约束 + 显式白名单；且落地时实测零违规，无既有噪音。
- **[守卫规则退化]** 候选集为空后永远绿 → **缓解**：R3"有牙"自检断言候选集规模下限。
- **[升级告警噪音]** 每轮巡检重复落盘 → **缓解**：`unhandled_for` 同类去重 + 既有 `escalation_cooldown_minutes`。
- **[改 `event_bus` 影响面]** recovery 是核心链路 → **缓解**：新增分支只对"`testing` 且无驱动"生效，`implementing` 既有语义不动；补单元测试钉住既有分支不回归。

## Migration Plan

1. 落地守卫（防线一/二）：纯新增测试 + 收紧 5 处替身，零生产变更，可独立先合。
2. 落地升级（防线三）：改 `admin_monitor` 异常分层 + 信号表，行为可测（TypeError→升级 / OSError→WARNING）。
3. 落地探测（防线四）：新增 `_detect_orphaned_state` + `event_bus` 恢复出口；先以较高阈值观察（保守），确认无误报再收紧。
4. 回退：防线一/二纯测试，删除即回退；防线三/四改的是新增分支，回退即删分支。

## Open Questions

- `orphaned_state` 阈值取 10 分钟还是 15 分钟？（倾向与 `admin.interval_minutes`（5）的整数倍对齐，避免巡检周期导致漏检，默认 15 = 3 个巡检周期。）
- 是否要把替身保真守卫进一步升级为强制 `create_autospec`？（更强但改动面大，建议作为后续独立小 spec。）
- `callsite-arity-guard` 是否扩展到 `bin/` 与 `agents/`？（当前只管 `core/` + `fenixd.py`，按需扩展。）
