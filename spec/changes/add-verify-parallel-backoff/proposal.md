# 提案：add-verify-parallel-backoff（inconclusive 重验并行度自适应降档）

## Why

add-spec-status-modal-budget 风暴（2026-09-09 16:07 → 09-10 00:40）实证：`max_parallel=5` 时被测实例渲染资源被 5 个并发浏览器 context 挤爆，web 场景批量首帧 8s 超时 → B1 白屏降级 blocked-env → 全批 inconclusive 重验——而重验并行度**不变**，同一过载条件原样复现，11 轮连续 blocked-env（每轮空跑 27 场景 ~95s + 实例准备 ~90s ≈ 3min 墙钟）。人工把 `max_parallel` 改 1 后第 12 轮零白屏零 blocked（19 warning 全为 SSIM 视觉抖动），一次通过 verified。

双证闭环：并行度 5 → 11/11 轮批量白屏；并行度 1 → 0/1 轮白屏。故障是**确定性资源瓶颈**而非间歇环境故障，但框架在「全批 blocked-env 疑似资源过载」这一明确信号下没有任何并行度自适应行为——inconclusive 门禁只会原样重派。

## What Changes

- **inconclusive 重验并行度按 attempt 递减**：`_handle_env_blocked_inconclusive` 判定重验时，按连续 blocked-env attempt 数计算降档并行度写入 spec attrs（`_verify_parallel_override`），下一轮 `VerifyEngine` 构造时读取并覆盖 `max_parallel`。递减序列：配置值 → 减半（向下取整，下限 1），即 5→2→1；配置值 ≤2 时直接 1。首轮（attempt 1）不降档——首轮白屏证据尚不存在，降档会冤枉健康环境。
- **健康轮自动复位**：任一轮验证非 inconclusive（出现真实 verdict：verified / bug-found / 或有效失败>0 的正常判定）时清 `_verify_parallel_override`，恢复配置并行度；与 `_inconclusive_attempts` 的既有清零点（人工解冻 / fast-track verified）同步。
- **降档可观测**：降档轮的引擎启动日志与 report 附有效并行度与降档来源标记，时间轴可见「因连续 blocked-env 降档至并行度 N」。

不做的事（YAGNI，用户已拍板）：
- **不做渲染层预检探针**——用户明确选择「不做预检，只做事后降档」；首轮空跑接受为已知成本（~3min），降档从第 2 attempt 起生效。
- **不做跨轮白屏率阈值触发**——按 attempt 递减不需要持久化白屏率状态文件，复用既有 `_inconclusive_attempts` 生命周期。
- **不改多探 HTTP 端点**——09-11 定案：本风暴 HTTP 层确实健康，多探 HTTP 端点探不出渲染层过载。

## Capabilities

### New Capabilities
- `inconclusive-parallel-backoff`: inconclusive 重验并行度自适应降档——连续 blocked-env 重验按 attempt 递减有效并行度（配置值→减半→下限 1），健康轮自动复位，降档可观测。

### Modified Capabilities
<!-- 无 requirement 级修改：归档能力 verify-environment-sanity-gate 的既有
     requirement（后置分类 / inconclusive 门禁 / 重验不烧信号预算）语义不变，
     本能力只在其重验分支上追加「并行度递减」行为；verify_engine 的 max_parallel
     配置语义不变（本能力不改配置值，只按轮覆盖有效值）。 -->

## Impact

- `core/pm_engine/verification.py`：`_handle_env_blocked_inconclusive` 写降档标记；有效失败>0 或 verified 分支清标记。
- `core/verify_engine/engine.py`：构造/启动时读 `_verify_parallel_override` 覆盖 `max_parallel`；启动日志与 report 透出有效并行度。
- `core/pm_engine/dispatch.py`：fast-track verified 清零点同步清 `_verify_parallel_override`（与 `_inconclusive_attempts` 同生命周期）。
- `core/state_machine.py`：解冻清零点同步清 `_verify_parallel_override`。
- 无 UI 变更；无配置键新增（递减规则内置常量，`inconclusive_max_attempts` 等既有配置不动）。
