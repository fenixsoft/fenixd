## Why

2026-09-21 `add-freeze-stop-inflight-agents` 卡死事故（judge 重跑 6/5 冻结，成本 $76 / 80M token，
实现预算 5/6）取证结论：**产品代码从头到尾正确，框架却烧穿预算**。

关键事实（均已回源码复核，非推测）：

- 修复代码在 main 的前端 / 后端 / dist 三处都在位；在**同一验证 serving 实例**上用 Playwright
  复现冻结流程，`freeze_spec` 返回 `stopped_agents: 1`、toast 渲染**正确文案**。
- 但验证轮每轮都记录同一场景 `web-freeze-inflight-stopped-hint` 失败，judge 每轮判 `product-bug`：
  ```
  02:02:46 改道门不放行（失败 1 个，product-bug=1，未分类 0）— 走现行 bug-found 路由
  03:56:17 改道门不放行（失败 1 个，product-bug=1，未分类 0）— 走现行 bug-found 路由
  ```
- `fail_history.json` 记录**连续三轮失败场景集完全相同**（round2/round3 failed_scenarios 逐字一致）。
- `_classify_fail_history`（`core/pm_engine/family.py:370`）**已经算出**这种情形是 `repeat`（无进展
  信号），但该结论**只用于拼告警文案**——原文是「…可能属误置情形，**建议人工核对**」，**不是闸门**。
- 框架已有的三道纠错通道全部失效在同一处：
  | 通道 | 为何没拦 |
  |---|---|
  | 场景缺陷改道门（`escalation.py:557`） | 判据要求 `product-bug==0`，judge 判 product-bug → 按设计不放行 |
  | 投机门禁（`escalation.py:996`） | 判据要求全部驱动场景 `speculative`；场景每轮重生成截图 → `evidence-backed` |
  | 同因重派熔断（`queue.py:1520`） | 作用域**显式排除** bug-found 路径（注释明写只在通用失败重派分支记账） |
- 最终破局的 admin 通道**被唤起但执行失败**：`blocked_stuck` → Administrator run 撞 HTTP 520 重试
  耗尽 → `exit 1` 静默死（无二次升级）。
- 三条硬上限（judge 重跑 5 / 验证失败 3 / 实现预算 6）各自独立、各自只冻结，且冻结 error 只写
  「judge 重跑超上限」，**把最有信息量的 `repeat` + 零差异诊断丢掉了**。

**本质缺陷**：框架把「验证失败」默认解释为「实现有缺陷」，并据此路由到「重派实现者」；当失败实为
**验证侧假失败**（不可复现 / 陈旧产物）时，该路由对根因零杠杆，而框架已算出的「无进展」信号停在
提示档，无人踩刹车。

## What Changes

一条 SPEC 内完成四项收敛治理（均复用框架已有零件，避免新增判据体系）：

1. **无进展循环闸门**：把 `repeat`（连续 N 轮失败场景集完全相同）从「告警文案」升级为**打回前闸门**。
   连续 `repeat` 达阈值 → **拒绝重派实现者**，改走「验证复核」（清裁决缓存 + 重验一次，复用投机
   门禁的预算范式）；预算耗尽 → blocked + 人工升级。判据纯机械、零 token。
2. **实质变更判定**：新增「实现者本轮是否有实质代码变更」判定——diff 统计**限定在本 SPEC
   `## Deliverables` 声明路径**上，忽略 `tasks.md` / `.fenix-run-result.json` 等元数据。声明路径零
   diff = 实现者对本次失败无杠杆，是循环闸门的**第二判据**（避免「勾选任务书冒充进展」绕过）。
3. **裁决缓存不得加固失败结论**：跨轮缓存命中 `product-bug` **且** 本轮无实质变更时，缓存结论
   **不得**直接驱动打回，必须触发一次复核（读侧降级，与既有 speculative 降级同族）。
4. **硬上限诊断贯通 + 升级通道可靠性**：① judge 重跑 / 验证失败 / 实现预算三条上限触发冻结时，
   MUST 把 `repeat` / 零实质变更诊断结论写进 `error` 与升级告警（人一眼看到「这是死循环，不是缺
   修复」）；② Administrator run 失败（CLI 退出 / 网关错误）MUST 有独立降级——至少落一条直接人工
   告警，不得静默死。

## Capabilities

### New Capabilities

- `verify-loop-convergence`: 验证假失败循环的收敛治理——无进展闸门（repeat + 实质变更双判据）、
  验证复核通道、裁决缓存降级、硬上限诊断贯通、升级通道失败降级。

## Impact

- 受影响代码：`core/pm_engine/family.py`、`core/pm_engine/verification/escalation.py`、
  `core/pm_engine/verification/pipeline.py`、`core/pm_engine/verification/branch_guard.py`、
  `core/pm_engine/verification/infra_classify.py`、`core/verdict_check.py`、
  `core/agent_runner/maintenance_runs.py`、`core/admin_monitor.py`。
- 行为影响面：新增一道打回前闸门 + 一处冻结诊断补全 + 一处 admin 失败降级。默认阈值下不改变
  「真·产品缺陷」路径（`repeat` 未达阈值或存在实质变更时行为逐字不变）。
- 不新增配置键外的 Dashboard 面（复用既有 `verify.*` 配置节，见 design D6）。
- 非目标：不改 judge 判据、不改 `VERDICT_CLASSES` 四类枚举、不引入验证产物指纹比对（另记 todo）。