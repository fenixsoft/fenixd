# 设计：add-verify-parallel-backoff

## Context

add-spec-status-modal-budget 风暴（2026-09-09/10）解剖定案（fenixd-env-gate-root-http-only-anatomy）：`max_parallel=5` 并发 5 个 Playwright context 挤爆被测实例渲染资源 → web 场景批量首帧 8s 超时（`_wait_stable` 返回 False）→ B1 白屏候选降级 blocked-env → `_handle_env_blocked_inconclusive` 全批 inconclusive 原样重派。重验并行度**不变**（`VerifyEngine.__init__` 恒从 `verify_engine.max_parallel` 配置读取，engine.py:83），同一过载条件 11 轮复现（11/11 批量白屏），每轮墙钟 ~3min（95s 引擎执行 + ~90s 实例准备）。人工改并行度 1 后第 12 轮零白屏一次通过（0/1），双证闭环。

既有 inconclusive 生命周期（复用，不新造状态）：
- 计数：spec attrs `_inconclusive_attempts`，`_handle_env_blocked_inconclusive` 每轮 +1（verification.py:137）
- 清零点：人工解冻（state_machine.py:580）、fast-track verified（dispatch.py:2566）
- 上限：`verify_engine.inconclusive_max_attempts`（默认 3）停自动重验、`inconclusive_escalate_attempts`（默认 4）写 SIGNAL 冻结

## Goals / Non-Goals

**Goals:**
- 连续 blocked-env 重验时有效并行度逐轮递减（5→2→1），让资源瓶颈轮在低并行度下自愈通过
- 健康轮（非 inconclusive）自动复位，恢复配置并行度
- 降档在日志与 report 可追溯

**Non-Goals:**
- 渲染层预检探针（用户拍板不做：首轮空跑 ~3min 接受为已知成本）
- 跨轮白屏率状态文件（按 attempt 递减零新增持久化）
- 多探 HTTP 端点（09-11 定案：HTTP 层本就健康，探不出渲染层过载）
- 修改 `verify_engine.max_parallel` 配置键语义或默认值（用户 config.yaml 不动）
- api/cli 场景并行度单独治理（本风暴瓶颈在 web 渲染，信号量是全局的不需要 per-kind）

## Decisions

### D1：降档信息流 = spec attrs 单字段，pm_engine 写、verify_engine 读

`_verify_parallel_override`（int，缺省缺失）存 spec attrs，与 `_inconclusive_attempts` 同生命周期同载体：

- **写端**：`_handle_env_blocked_inconclusive` 在 attempts≥2 的重验分支（`attempts < max_attempts`）计算 `override = max(1, base >> (attempts - 1))`（base=配置 max_parallel）随 `update_spec` 一并写入；attempts==1 的重验分支不写（首轮不降档——白屏证据尚不存在，降档会冤枉健康环境）。
- **读端**：`verification.py` 构造 `VerifyEngine` 处（:1583）读 spec 的 `_verify_parallel_override`，非空则设 `engine.max_parallel = override`（引擎构造参数不动，保持既有测试兼容）。
- 递减公式选右移（减半向下取整、下限 1）：5→2→1 三轮内触底，与 `inconclusive_max_attempts=3` 自然对齐——第 3 attempt 已是并行度 1，若仍全批 blocked-env 则走既有停验/升级通道，不需要更深的递减。

### D2：复位点与 `_inconclusive_attempts` 完全同生命周期

| 既有清零点 | 同步清 `_verify_parallel_override` |
|---|---|
| 人工解冻 unfreeze（state_machine.py:580） | ✓ 同一原子写 |
| fast-track verified（dispatch.py:2566） | ✓ 同一 update |
| 非 inconclusive 正常轮（本 SPEC 新增） | ✓ `_handle_env_blocked_inconclusive` 返回 False 的判定分支 + verified/bug-found 落点 |

不引入独立过期机制：字段只被 inconclusive 链路读写，链条断即复位，无泄漏面。

### D3：可观测走既有通道

- 引擎启动日志（engine.py:175 处）：有效并行度后附「（inconclusive 降档）」标记，仅在 override 生效时出现。
- report.json 顶层新增 `effective_parallel`（int）——所有轮都写（正常轮=配置值），降档语义由值与配置值的差 + 日志标记承载，不新增布尔键。

### D4：降档只影响并行度，不动退避/超时参数

场景超时（首帧 8s、断言窗口等）不随降档调整——串行实证全绿即在既有超时预算内，改超时会掩盖真实慢场景。

## Risks / Trade-offs

- **首轮空跑成本保留**（用户接受）：attempt 1 不降档意味着风暴首重验轮仍按原并行度空跑 ~3min；降档从第 2 重验轮起生效。换取的是零新增探针机制与零误降档（首轮无证据）。
- **非 web 瓶颈的全批 blocked-env 也会被降档**：如实例真死（HTTP 失联）时降档无益但也无害——探针失联时候选本就全部降级 blocked-env，与并行度无关；降档轮仍 blocked 只会更快走到停验/升级通道。
- **`_verify_parallel_override` 与用户手改 config.yaml 竞争**：降档值只在 override 存在时生效且健康即清，用户手改配置值在下次降档计算时以新值为 base，无固化。
- **递减过快错过中间最优点**（5→2 跳过 3/4）：递减的目的是「触底自愈」不是「寻优」，2 或 1 都足以解除本实证的过载形态；更细粒度只拉长风暴收敛轮数。
