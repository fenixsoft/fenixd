# SPEC 生命周期与状态机

Fenix 将 SPEC 的从提出到发布的完整生命周期建模为**10 个状态**的有限状态机。本章覆盖全部状态、合法转移、打回与修复循环、冻结机制与门禁逃生门。

## 状态全景

```mermaid
stateDiagram-v2
    [*] --> drafted: /fenix-new 创建 SPEC
    drafted --> ready: 设计+任务书完成
    ready --> implementing: 调度派发 implementer
    implementing --> implemented: 实现完成
    implementing --> ready: 重试
    implementing --> blocked: 熔断/冻结
    implemented --> testing: 验证流水线启动
    testing --> verified: 门禁判定通过
    testing --> bug-found: 验证发现缺陷
    bug-found --> implementing: 修复重派
    bug-found --> implemented: fix 完成重新验证
    verified --> done: 自动推进（等待审批）
    done --> pushed: /fenix-approve 推送
    blocked --> ready: 人工恢复/解冻
    pushed --> [*]
```

## 各状态详解

### drafted（草稿）

- **进入条件**：`/fenix-new` 创建 SPEC
- **离开条件**：设计文档与任务书完成 → `ready`
- **含义**：SPEC 刚创建，还在设计阶段

### ready（就绪）

- **进入条件**：设计完成；或被熔断后人工恢复
- **离开条件**：被 PM 调度派发 → `implementing`
- **含义**：等待调度引擎按优先级派发

### implementing（实现中）

- **进入条件**：PM 派出 implementer
- **离开条件**：
  - `implemented`：实现完成
  - `ready`：实现重试（工作流打回）
  - `blocked`：达到 impl_run_budget 触发熔断、或人工冻结
- **含义**：实现者正在 worktree 中编写代码

### implemented（已实现）

- **进入条件**：实现完成
- **离开条件**：验证流水线启动 → `testing`
- **含义**：代码已合并，等待验证

### testing（验证中）

- **进入条件**：验证流水线启动
- **离开条件**：
  - `verified`：门禁判定通过
  - `bug-found`：验证发现缺陷
- **含义**：验证者正在构建、启动实例并执行场景

### verified（已验证）

- **进入条件**：planner-judge 门禁判定通过
- **离开条件**：`done`（自动推进，无需人工操作）
- **含义**：验证通过，等待推进到 done

> **门禁逃生门**：`verified → testing` 仅允许由门禁拦截触发的自动回退调用（`_on_spec_verified` 门禁发现应用不可达或证据不足时自动回退），人工路径无法直接执行该转移，无法绕过验证门禁。

### bug-found（发现缺陷）

- **进入条件**：验证发现缺陷，验证报告闸门放行
- **离开条件**：
  - `implementing`：修复重派（fix 分支）
  - `implemented`：fix 完成后直接重新验证
- **含义**：进入修复循环。

### blocked（阻塞）

- **进入条件**：
  - 达到 `impl_run_budget` 实现尝试预算上限（熔断）
  - 连续合并失败达到阈值
  - 人工冻结
- **离开条件**：`ready`（人工恢复/解冻后）
- **含义**：自动链已停止，等待人工决策。

### done（完成）

- **进入条件**：`verified` 自动推进
- **离开条件**：`pushed`（`/fenix-approve` 审批推送；`approve_mode: auto` 时自动推送）
- **含义**：验证通过，等待唯一人工门禁审批。

### pushed（已推送）

- **进入条件**：审批通过并推送远程仓库
- **离开条件**：无（终态）
- **含义**：交付物已发布，SPEC 生命周期结束。

## 完整合法转移表

| 当前状态 | 可转移目标 |
|---------|-----------|
| drafted | ready |
| ready | implementing |
| implementing | implemented, ready（重试）, blocked（熔断） |
| implemented | testing |
| testing | verified, bug-found |
| bug-found | implementing（修复）, implemented（fix 后重验） |
| blocked | ready |
| verified | done |
| done | pushed |
| pushed | （无，终态） |

## 打回与修复循环

验证失败 → `bug-found` → 修复循环：

1. 验证报告说明缺陷根因
2. 派发 fix 分支（`fix-<name>` 后缀）给 implementer 修复
3. 修复完成 → `implemented` → 重新走验证流水线
4. 验证通过 → `verified` → `done`

> fix 族谱有深度/宽度上限（默认深度 3、宽度 2），防止无限派生。越界触发 `family_explosion` 困境信号转人工处置。

## 冻结与解冻

**冻结**（`/fenix-freeze` 或 Dashboard 冻结操作）：写入 blocked + 结构化 `frozen: true` 标记 + 规范前缀 error。冻结期间所有自动链路对状态的改写被剥离，唯一出路是解冻。

**解冻**（`/fenix-unfreeze`）：恢复冻结前状态并清空 error；未冻结时是幂等 no-op。

## Daemon 重启中断恢复

SPEC 处于 `implementing`/`testing` 这类中断状态时，daemon 重启自动回退到 `ready`，清空陈旧 run 字段并重置重试计数，重新进入调度池。

## 门禁系统：两步判定

验证流水线结束后，门禁法官（planner-judge）进行判定：

1. **应用可达性门禁**：被测实例不可达且场景全失败时不判定 verified（防止测到陈旧产物）
2. **验证报告门禁**：报告缺失或缺失场景结果时阻止推进 bug-found（防止伪失败级联）

> 门禁无法在 CLI/Dashboard 直接绕过。`verified → testing` 逃生门仅门禁自身自动调用。

## STATE.md 与时间轴

- **STATE.md**：项目根的 `STATE.md` 记录每个 SPEC 的状态字段、优先级、创建/更新时间、run 引用、error 等。格式详见 [文件与数据地图](09-artifacts.md)。
- **时间轴**：Dashboard「运维记录」页展示 Administrator 活动时间线；`/fenix-process <name>` 展示单个 SPEC 时间线。

## 相关文档

- [验证体系](05-verification.md) — 三步流水线与门禁判定细节
- [调度与治理规则](06-governance.md) — 预算、熔断、人工恢复
- [FAQ 与故障排查](10-faq.md) — SPEC 卡住怎么办