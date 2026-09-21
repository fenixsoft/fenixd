## Why

2026-09-21 一轮 daemon/dashboard 重启运维中暴露两个可靠性缺陷，均会导致「已完成的工作静默丢失或被打断」：

1. **STATE.md 写入非原子**：`StateMachine.update_spec` 的 `read_all()` 与 `write_all()` 不在同一把文件锁内，并发的两个更新会互相覆盖（丢失更新）。实证：解冻 3 个 spec 后 daemon 并发派发评审，某 spec 的 `reviewer_run`（日志 04:45:49.938 明确写入）被更早快照（`updated=04:45:49.186`）覆盖回 `null` → `consume_review_result` 开头 `if not run_id: return False` 静默早退 → 评审 run 已收工、结果文件已合法落盘，但状态机永不推进、spec 永停 reviewing。同一竞态还会清掉冻结时写入的 `error`（含「原状态 reviewing」），使解冻只能回退 `ready` 而非原状态。

2. **stale_code_selfheal 的「空闲」判定误伤在飞 run**：`_is_idle()` 在评审 run 停滞（如 API 长重试期转录无增长）时判为空闲，连续 120s 后触发自愈 `touch restart_request`，SIGTERM 杀掉正在跑的评审 run，打断分钟级工作。

两者都是「运行期状态一致性」问题：一个让已落盘的结果无法被消费，一个让在飞的工作被自愈重启打断。

## What Changes

- **STATE.md 写入原子化**：`update_spec`（及其它 read-modify-write 写入路径）的「读 → 改 → 写」收进同一把 `.STATE.md.lock` 内，消除并发丢失更新。对齐既有 `_bump_counter` 的「锁内原子读改写 + 回读校验」范式。
- **关键字段可靠持久化**：冻结写入的 `error`（含「原状态 X」）在并发下 MUST NOT 被静默清除；解冻（`unfreeze` / `consume_review_result`）能读到真实原状态。
- **自愈重启安全边界**：`stale_code_selfheal` 的空闲判定 MUST 把「存在未收口的在飞 run（含停滞/重试中）」视为非空闲，自愈 MUST NOT 打断在飞评审/实现 run。补齐「停滞中的 run 仍算占用」的判定。
- **回归覆盖**：新增并发写入（模拟两线程 read-modify-write 交错）与自愈重启安全（停滞 run 存在时不触发）的契约测试。

无对外 API/配置格式变更；`gates.start_after_scope` 等既有语义不变。

## Capabilities

### New Capabilities
- `state-write-atomicity`: STATE.md 状态写入的原子性与并发安全——并发写入 MUST NOT 丢失更新；冻结 error / run 锚点等关键字段 MUST 可靠持久化并可被解冻正确读取。

### Modified Capabilities
- `stale-code-selfheal`: 「空闲感知的陈旧自愈触发」Requirement 加强——空闲判定 MUST 纳入在飞 run 的全部形态（含停滞、API 重试中、转录暂不增长），MUST NOT 在其存在时触发自愈重启。

## Impact

- **代码**：`core/state_machine.py`（`update_spec` / `write_all` / `_write_all_locked` 及相关 read-modify-write 路径）、`fenixd.py`（`_is_idle` / `_maybe_stale_selfheal_tick`）、必要时 `core/pm_engine/`（在飞 run 计数的语义核对）。
- **数据**：`.fenix/STATE.md`（运行期，gitignored，无交付物影响）。
- **测试**：`tests/` 新增并发写入原子性与自愈重启安全用例；既有状态机测试零回归。
- **风险**：状态机写入路径是核心链路，加锁需避免死锁（同进程重复 flock 会阻塞，参照 `_write_all_locked` 既有约束）；空闲判定加强需避免「停滞 run 永久占位导致自愈永不触发」的另一极端。