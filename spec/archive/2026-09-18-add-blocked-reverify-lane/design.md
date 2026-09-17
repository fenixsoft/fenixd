# 设计：add-blocked-reverify-lane

## Context

add-proxy-tunnel 事故（fenix-server 2026-09-10）实证了两个结构性缺陷的合力：env 阻塞复位必走全量重实现（根因 A），复位清零让冻结门永不可达（根因 D）。本设计只动复位路径与计数语义，不碰 env 判定、升级触发与 fix 通道。

关键现状（fenixd 本仓库 HEAD，与 fenix-server 部署同构）：

- `core/state_machine.py:120` `VALID_TRANSITIONS`：BLOCKED 仅 [READY]；`:137` `GATE_TRANSITIONS`：仅 VERIFIED→[TESTING]（D7 逃生门先例，verifier-judgment-integrity）；`:671` `transition_gate()` 守卫实现（幂等自迁移短路已内置）。
- `core/pm_engine/verification.py:2843` `_escalate_env_blocked`：`rounds = int(spec.get("_env_block_rounds") or 0) + 1`，`frozen = rounds >= 2`；写入 blocked + error + rounds。清零点两处（verified 落定，`:2174` 与 `:2774`）——这两处保留。
- `core/pm_engine/verification.py:2902-2932`（近似）自动呼叫 Administrator 经 `request_admin_invoke`，提示词含「处置完成后触发该 spec 重新验证」——admin 因此被迫手动 StateMachine 旁路复位（事故实录：admin-1 12:49:11 `sm.transition('add-proxy-tunnel','ready')`）。
- `core/admin_monitor.py` 消费 disposition（result=resolved/partially-resolved/escalated 判定在 `:1032` 附近）；`core/agent_runner/runner.py:1069` `run_administrator` 是 admin 侧写入口。
- `core/event_bus.py:187` `_recover_ready`：孤儿 ready 恢复。复位到 testing 后 spec 短暂处于 testing 态，重验由 verifier 入队自然接管，`_recover_one` 的 implemented 分支已有 tester_run/暂停标记防重触发先例——testing 态本身不在 recovery 白名单（INTERRUPTED_STATES 才回退），无新增恢复风险，但需回归确认。

## Goals / Non-Goals

- Goals：env 阻塞复位在实现已合并时零实现轮直达重验；`_env_block_rounds` 生命周期累计、冻结门可达；admin 处置闭环不再依赖手动状态操作。
- Non-Goals：不改 env 失败判定与洗白门禁；不动 bug-found 修复通道；不实现验证环境预检清理（另案）；不改 admin 成本侧车记账（另案）；fast-track 车道不接入（无 verifier 车道）。

## Decisions

### D1. 复用 GATE_TRANSITIONS 逃生门模式，扩展 BLOCKED: [TESTING]

`GATE_TRANSITIONS[SpecStatus.BLOCKED] = [SpecStatus.TESTING]`。理由：

- 先例完整：VERIFIED→TESTING 逃生门（D7）已验证「白名单 + 专用守卫方法 + 人工路径仍受限」三层约束，`transition_gate()` 幂等短路、GATE_TRANSITIONS 拒绝分支全部现成。
- 与另起 `BLOCKED→TESTING` 进 VALID_TRANSITIONS 相比：后者会让人工路径自由直达 testing，破坏「重验直通道只在守卫条件满足时放行」的设计意图。

守卫条件（调用方负责，transition_gate 只管白名单）：status=blocked、非人工冻结（frozen != True 且 error 不以冻结前缀开头）、branch 非空、branch merge commit 存在于主树历史（`git merge-base --is-ancestor <branch> HEAD`，subprocess 带 timeout，异常按「未合并」处理回退 ready 通道）。

### D2. 复位判定内建在 admin_monitor 处置收尾消费点

消费点位置：admin_monitor 摄取 disposition 最终结果（result ∈ resolved/partially-resolved）处。判定顺序：

1. signal_type ∈ {verify_env_blocked, verify_env_inconclusive}（env 族信号才走重验判定；其余信号类型复位语义不动）。
2. spec 现态为 blocked 且非人工冻结。
3. branch 已合并（D1 守卫）→ `transition_gate(spec, "testing")` + 清 error（保留 rounds）+ verifier 经既有 spec_implemented 等价路径入队（复用 `_on_spec_implemented` 的入队，直接调 `pm_engine.handle_event("spec_implemented", spec)` 最小侵入——fast-track spec 在该 handler 已有跳过分支，天然安全）。
4. 未合并/无 branch → 既有 `transition(spec, "ready")` + 清 error（不清 rounds）。

同时在 admin prompt（`verification.py` 自动呼叫文本 + `admin_monitor.py` 信号建议文本 + prompt_builder administrator 模板）三处声明「处置范围限于环境修复，不要手动 reset spec 状态；框架将在处置收尾自动触发重验证」。

兼容：admin/用户手动复位到 ready 的路径不做拦截（Dashboard unfreeze、手动 StateMachine 写法保持现状可用），手动路径同样不清 rounds。

### D3. `_env_block_rounds` 常量化 + 清零点收敛

- 新增常量 `ENV_BLOCK_ROUNDS_FIELD = "_env_block_rounds"`（state_machine.py 字段名单区，IMPL_RUN_BUDGET_USED_FIELD 同款），verification.py 升级通道与清零点改引常量（防字符串漂移；`_` 前缀侧车序列化已天然持久化，无需改 serialize 白名单）。
- 清零点收敛：保留 verified 落定两处（`:2174`/`:2774`，与 `_verify_fail_rounds` PASS 唯一归零点同语义）；`unfreeze_spec` 增清该字段（与 `_inconclusive_attempts`/`_verify_redo_count` 人工解冻清零同款，同一原子写）。其余路径（处置复位、恢复、fix 链）不动该字段即达成不清零。

### D4. 边界与回归

- 实现阶段熔断（implementing→blocked，无 branch）：复位走 ready 通道，行为零变化。
- 重验再次阻塞：rounds=2 → 冻结转人工（既有 `_escalate_env_blocked` frozen 分支），止损窗口收窄为「一次 admin 修复机会」。
- event_bus `_recover_ready` 不感知 testing 态（testing 不在 recovery 白名单），复位后 verifier 入队即正常流转；daemon 重启时 testing ∈ INTERRUPTED_STATES 会重置为 ready——**接受此现状**（重启丢失的仅是一次 14 秒级重验，verifier 从 ready 重派的全量路径仍在），不为此扩 INTERRUPTED_STATES 处理。
- 回归重点：人工 `transition(blocked→testing)` 仍被拒；`transition_gate(blocked→testing)` 在守卫不满足（未合并）时由调用方不发起（transition_gate 本身只查白名单）；READY 通道行为零变化；fix 通道（bug-found→implementing）零变化。

## Risks / Trade-offs

- 「快速再次阻塞」窗口：环境修复不彻底时重验 14 秒即再阻塞，比现状（先烧一轮 implementer 再阻塞）反而更早暴露、成本更低；rounds 生命周期累计保证第 2 次必冻结。
- `git merge-base --is-ancestor` 判定依赖 worktree 布局：统一在主树 project_root 执行；subprocess 异常 fail-safe 回退 ready 通道（宁可多重实现不可错误直达）。
- admin 提示词三处文本需同步修订（verification.py / admin_monitor.py / prompt_builder 模板）——漏改一处仅导致 admin 仍可能手动复位，行为退化为现状，不产生新故障。

## Migration Plan

纯框架行为变更，无数据迁移。存量 spec 的 `_env_block_rounds` 值（0 或历史 1）天然兼容新语义。

## Open Questions

- 无。阈值维持 2（用户拍板「第 2 次即冻结」）；重验直通道不设 per-spec 开关（守卫条件已足够保守）。
