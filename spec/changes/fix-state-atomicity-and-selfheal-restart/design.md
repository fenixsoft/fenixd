## Context

`.fenix/STATE.md` 是 daemon 的 SPEC 状态机存储，唯一写入者是 `core/state_machine.py:StateMachine`。

**当前写入形态**：`update_spec`（:701）执行 `specs = self.read_all()` → `specs[name].update(updates)` → `self.write_all(specs)`。其中 **read 与 write 之间不持锁**——`write_all` / `_write_all_locked`（:566）自身才加 `.STATE.md.lock` 的 flock。并发的两个 `update_spec`（daemon 的多个 worker 线程 + dashboard 独立进程）会各自读到同一份快照、各自改一处、各自整体写回，后写者用陈旧快照覆盖先写者的改动（丢失更新）。

**既有正例**：`_bump_counter`（:596）已采用「锁内 read→改→`_write_all_locked`→回读校验」范式（fix-budget-counting-semantics D2），证明该修法在本代码库可行且已被验证。

**2026-09-21 实证（本 SPEC 的触发事故）**：
- 解冻 3 个 spec 后 daemon 并发派发 3 个评审 run；`add-timeline-gate-failure-display` 的 `reviewer_run` 于 `04:45:49.938` 被写入，但 STATE.md 落定值来自 `04:45:49.186` 的旧快照（`updated` 字段可证），`reviewer_run` 回退 `null` → `consume_review_result` 开头 `if not run_id: return False` 静默早退 → 评审 run 已收工、结果文件已合法落盘，spec 永停 `reviewing`。
- 同一竞态在冻结路径上表现为：`freeze_for_human` 写入的 `error`（内嵌「原状态 reviewing」，是 `parse_orig_status` 解冻目标解析的唯一来源）在后续被清为 `null`；实测 STATE.md 全部 277 条 spec 的 `error` 均为 `null`，`grep -c "用户指令冻结"` = 0。解冻只能回退 `ready`（而非原状态）。

**当前 `_is_idle`（fenixd.py:979）**：`pm_engine._active_runs == 0` 且 admin 池无在途。2026-09-21 事故：评审 run `spec-review-add-code-review-auto-fix-1789964873` 在 API 520 长重试期转录不增长，被判为空闲，连续 120s 后 `stale_code_selfheal`（fenixd.py:1001 `_maybe_stale_selfheal_tick`）写入 `restart_request`，supervisor SIGTERM 杀掉该在跑 run。

## Goals / Non-Goals

**Goals:**
- STATE.md 的所有 read-modify-write 写入在并发下 MUST NOT 丢失更新（消除 `update_spec` 竞态）。
- 冻结写入的 `error`（含「原状态 X」）MUST 可靠持久化，直至解冻被正确读取。
- `stale_code_selfheal` MUST NOT 在存在未收口在飞 run（含停滞/API 重试中）时触发重启。

**Non-Goals:**
- 不改 STATE.md 的文件格式、字段集合与序列化形态。
- 不改 supervisor 的 `restart_request` 协议语义（自愈仍复用该协议）。
- 不重写状态机整体（仅收敛写入原子性 + 加强空闲判定）。
- 不处理模型链 failover（`maomaoai/deepseek-v4.1-flash` 无效模型名导致评审 `Exit code:1` 冻结）——那是配置侧问题，另行处置，不在本 SPEC。

## Decisions

### D1: `update_spec` 收进 `.STATE.md.lock` 内的 read-modify-write
把 `read_all` → mutate → 持久化 三段收进同一把 `.STATE.md.lock` 的 `flock(LOCK_EX)` 内，采用 `_bump_counter` 同款范式。**备选**：乐观 CAS 重试（改动面更大、需给 STATE.md 加版本号）；全进程单例锁（不适用——dashboard 是独立进程，必须跨进程文件锁）。**约束**：同进程对同一文件重复 `flock` 会自阻塞（`_write_all_locked` 注释已载明），故锁内 MUST 调 `_write_all_locked` 而 MUST NOT 再调 `write_all`。

### D2: 同源收敛所有 STATE.md 写入路径
`add_spec` / `remove_spec` / `update_spec` / `_bump_counter` 统一走 D1 的锁内原子路径；核查是否存在无日志的直接 `write_all` 调用点（2026-09-21 观测到一次 `updated=03:43:24` 的写入在日志中**无对应 "Updated SPEC" 记录**，指向非 `update_spec` 路径，需在实现期定位并一并收敛）。

### D3: 空闲判定纳入「未收口的在飞 run」
`_is_idle()` 的判据 MUST 覆盖 run 的全部形态：除 `pm_engine._active_runs == 0` 外，MUST 核对 run 进程存活但 transcription 暂不增长（API 重试/停滞）时是否仍计入 active；若 `_active_runs` 在停滞期被误减，MUST 以「在册 run 未收口」补正。**反向约束**：对确已死亡/收口的 run MUST NOT 永久占位（否则自愈永不触发）——以 run 的终态/进程存活为界，不引入新的永真条件。

### D4: 回归以「并发交错」与「停滞 run」两个契约为锚
新增测试 MUST 能复现原缺陷：① 两线程/两路径并发 `update_spec` 不同字段，断言两个字段的改动都保留（当前实现会丢一个）；② 冻结 error 在一次并发写入后仍可被 `parse_orig_status` 读出原状态。③ 构造一个「登记在册但转录停滞」的 run，断言 `_is_idle()` 返回 False、`restart_request` 不被写入。

## Risks / Trade-offs

- **[加锁引入死锁]** → 严格遵循「锁内只用 `_write_all_locked`」，禁止锁内再 `write_all`；沿用 `_bump_counter` 已验证的调用结构。
- **[锁粒度变粗致写放大]** → 单进程内写入本已串行；跨进程（dashboard）写入频率低，可接受。
- **[空闲判定加强致自愈永不触发]** → 以「run 是否收口/进程是否存活」为界，不用转录新鲜度作唯一依据（停滞 run 转录本就不增长）；确保死亡 run 会被正常清理出在册集合。
- **[error 清理路径未定位]** → 若实现期仍无法定位 03:43:24 的写入者，则以 D1/D2 的锁内原子化兜底（原子写保证任何路径都不会用陈旧快照覆盖 error），并在测试中固化「冻结后任意并发写不丢 error」。

## Migration Plan

纯代码修复，无数据迁移。上线即通过 daemon 优雅重启（`restart_request`）载入新代码生效。回滚 = 回退代码版本。

## Open Questions

- 2026-09-21 `updated=03:43:24` 那次「无日志写入」的确切调用者（候选：直接 `write_all` 路径 / 跨进程写入）——实现期须以「写入必留痕」为目标补齐可观测性。
- 停滞 run 的「在册未收口」判据具体字段（`_active_runs` vs registry vs run 流文件末行终态）——实现期核对 `_is_idle` 上游计数的递减时机后定夺。