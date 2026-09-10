# scenario-defect-reroute-gate

场景缺陷改道门：judge 申报 bug-found 后、打回 implementer 前，框架机械判定 bug 清单的 classification 分布——纯场景缺陷清单不得消耗实现轮预算，强制改道 judge 原地修复通道；并固化 judge 侧场景修复路由的 prompt 约定。

## ADDED Requirements

### Requirement: bug-found 分类改道判定

系统 SHALL 在 judge 申报 bug-found 后、派发修复（`_on_spec_bug_found`）前读取本轮 verification report 的场景 classification 分布，执行改道判定：

- 本轮存在 failed 场景，且全部 failed 场景的 classification 均为**显式** `test-defect` 或 `flaky`（`product-bug` 计数为 0）→ 触发改道；
- classification 缺失（None）或值不在 {product-bug, test-defect, flaky, env} 内 → 视为不满足改道条件（保守：走现行 bug-found 路由）；
- 存在任一 `product-bug` → 不触发改道（现行路由不变）。

改道判定 SHALL 为纯 Python 机械判定（零 token），判定结果与依据（分布统计）SHALL 记入日志留痕。

#### Scenario: 全场景缺陷清单触发改道

- **WHEN** judge 申报 bug-found，report 中 19 个 failed 场景 classification 全部为 test-defect
- **THEN** 框架拒绝打回 implementer，进入定向重派 judge 流程

#### Scenario: 含产品缺陷不触发改道

- **WHEN** judge 申报 bug-found，failed 清单中 ≥1 个 classification=product-bug
- **THEN** 框架按现行路由派发修复，行为与无改道门时一致

#### Scenario: 未分类保守不改道

- **WHEN** judge 申报 bug-found，failed 清单全部 test-defect 但其中混有 classification=None 的条目
- **THEN** 框架不触发改道，按现行 bug-found 路由处理

### Requirement: 定向重派 judge 协议

触发改道时，系统 SHALL 重派 judge（planner-judge）一次，prompt SHALL 附加定向指令段，指令内容 MUST 包含：①上轮裁决清单全部为场景缺陷（product-bug=0）的统计事实；②按场景文件原地修复协议处置（申报 scenario-repaired），MUST NOT 申报 bug-found；③修复已裁决场景（含跨轮写回场景）合法，受冻结 diff 记账保护（无理由移除才被确定性补齐），不视为冻结违规。定向重派后 judge 申报 scenario-repaired → 沿用既有 judge-scenario-repair 通道重入（serving 缓存重执行场景）。

#### Scenario: 定向重派后 judge 原地修复

- **WHEN** 改道触发，judge 重派后申报 scenario-repaired（附修复清单）
- **THEN** 框架按既有 scenario-repaired 语义冻结记账并重入场景执行，不再消耗实现轮预算

#### Scenario: 定向重派后 judge 发现真实产品缺陷

- **WHEN** 改道重派后 judge 申报 bug-found 且清单含 product-bug
- **THEN** 框架按现行 bug-found 路由派发修复（改道门不再拦截含 product-bug 的清单）

### Requirement: 改道预算与升级路径

定向重派 SHALL 计入既有场景修复预算（`_SCENARIO_REPAIR_MAX_ROUNDS`=2，与 scenario-repaired 重入共用计数）；预算耗尽后 judge 仍申报 bug-found 且 product-bug=0 时，系统 SHALL 停止重派，向人工升级（告警附：失败场景清单、classification 分布、judge 各轮申报记录、静态扫描 findings 路径），spec 保持 testing 状态等待人工裁决。改道路径 MUST NOT 消耗实现尝试预算（impl_run_budget）。

#### Scenario: 预算耗尽升级人工

- **WHEN** 改道重派用尽 2 轮预算，judge 仍申报全 test-defect 的 bug-found
- **THEN** 框架发送人工升级告警（附清单与 judge 行为记录），spec 保持 testing，不再重派也不再打回 implementer

#### Scenario: 改道不消耗实现预算

- **WHEN** 一次完整改道流程发生（判定 + 重派 + scenario-repaired 重入）
- **THEN** 该 spec 的 impl_run_budget used 计数不变

### Requirement: judge prompt 场景修复路由约定

judge（planner-judge）prompt 模板 SHALL 将「场景文件缺陷 → 原地修复（scenario-repaired）」的处置指引置于 test-defect 分类定义处（与分类判定同位置），内容 MUST 包含：归 test-defect 时若根因在场景文件本身（{scenarios_path}，而非 tests/ 下 harness 代码），MUST 走原地修复协议申报 scenario-repaired，MUST NOT 将该场景写入 bug 清单走 bug-found（「场景文件问题派 implementer 是错误路由」）；并显式声明修复已裁决场景（含跨轮写回场景）合法、受冻结 diff 记账保护、不视为冻结违规。

#### Scenario: prompt 含同位置路由指引

- **WHEN** 构建 planner-judge prompt
- **THEN** test-defect 分类定义处含「场景文件缺陷 → 原地修复」指引与已裁决场景修复合法性声明，文末协议段保留协议细节
