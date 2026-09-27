# 场景缺陷改道门
<!-- knowledge: capability=scenario-defect-reroute-gate rev=1 sources=spec/archive/2026-09-15-add-scenario-defect-triage-gate -->

judge 申报 bug-found 后的机械改道判定：纯场景缺陷清单不消耗实现轮预算，强制改道 judge 原地修复通道。

## 现行规则

- 场景验收缺陷的基线闭环：场景自身缺陷（如相对 navigate 白屏）走退回 plan 重规划修正，不误判为产品缺陷。
- bug-found 分类改道判定：judge 申报 bug-found 后、派发修复（`_on_spec_bug_found`）前，读取本轮 verification report 的场景 classification 分布——本轮存在 failed 场景且全部 failed 场景的 classification 均为显式 `test-defect` 或 `flaky`（product-bug 计数为 0）→ 触发改道；classification 缺失（None）或不在 {product-bug, test-defect, flaky, env} 内 → 保守不改道（走现行 bug-found 路由）；含任一 `product-bug` → 不改道。判定为纯 Python 机械判定（零 token），结果与分布统计记日志留痕。
- 定向重派 judge 协议：触发改道时重派 judge（planner-judge）一次，prompt 附加定向指令段——上轮清单全部为场景缺陷（product-bug=0）的统计事实、按场景文件原地修复协议处置（申报 scenario-repaired）且不得申报 bug-found、修复已裁决场景（含跨轮写回场景）合法且受冻结 diff 记账保护（无理由移除才被确定性补齐）。定向重派后 judge 申报 scenario-repaired → 沿既有 judge-scenario-repair 通道重入（serving 缓存重执行场景）；重派后 judge 发现真实产品缺陷（清单含 product-bug）→ 按现行 bug-found 路由派发修复。
- 改道预算与升级：定向重派计入既有场景修复预算（`_SCENARIO_REPAIR_MAX_ROUNDS=2`，与 scenario-repaired 重入共用计数）；预算耗尽后 judge 仍申报纯场景缺陷 bug-found 时停止重派，升级人工（告警附失败场景清单、classification 分布、judge 各轮申报记录、静态扫描 findings 路径），spec 保持 testing 等待人工裁决。改道路径不消耗实现尝试预算（impl_run_budget）。
- judge prompt 路由约定：「场景文件缺陷 → 原地修复（scenario-repaired）」的处置指引置于 prompt 中 test-defect 分类定义处（与分类判定同位置），并显式声明修复已裁决场景合法、不视为冻结违规；场景文件问题（`{scenarios_path}` 而非 tests/ 下 harness 代码）不写入 bug 清单走 bug-found。

## 溯源

- 史前复原（存量基线） — 场景验收缺陷走退回 plan 闭环：场景自身缺陷回到重规划修正，不误判为产品缺陷
- 2026-09-15 add-scenario-defect-triage-gate — 新增 bug-found 前的 classification 分布机械改道判定、定向重派 judge 协议、改道预算与人工升级路径、judge prompt 场景修复路由约定（此前 100% 场景缺陷的清单照单消耗实现轮整轮修场景文件）
