# fix-verdict-env-exemption-admin-handshake

## Why

2026-09-25 add-session-composer 验证暴露接缝漏洞：原始 report.json 为 19 passed + 2 failed + 1 blocked_env + 1 warning（混合形态），既有三道环境防御（pipeline 阶段 2.5 应用不可达升级 / 阶段 2.6 全批 blocked-env inconclusive / 阶段 2.7 同因失败哨）全部以原始 summary 口径在 judge 之前判定，均未命中；随后 judge 裁决 agent 把 2 个 failed 单方面归类 env（豁免清单 7 条）并自我批准 verified——env 豁免不回流任何升级计数器，admin 全程未介入，dist 陈旧无人现场重建、事件源不可达无人诊断，「失败告警先呼叫 admin、admin 确认无法解决再升级人工」的规则在混合形态 + 裁决豁免组合下完全失明。fail-open 的正确语义是「框架穷尽自动化补救后仍无法解决才留报告给人」，当前实现缺的正是补救动作与握手环节。

## What Changes

- 裁决采纳尾段新增 env 豁免握手：judge 裁决产出 env 归类（豁免清单非空）时，MUST NOT 直接落 verified——回灌 inconclusive 重验链（复用既有 `_inconclusive_attempts` 计数、重验上限、超限 SIGNAL admin 的 B7 升级通道），重验前先执行环境补救探针（dist 新鲜度探针）；admin 确认环境不可解后豁免方可生效。
- 混合形态纳入 inconclusive 判据：扩展 `_handle_env_blocked_inconclusive` 入口（escalation.py:68 现只认全批 blocked-env），「原始 failed>0 但裁决/探针判定全部为环境性」的轮次同样按 inconclusive 处理，不再当健康轮放行。
- serving 层新增 dist 新鲜度探针：verify run 前比对 dashboard static src 与 dist 产物时序，dist 滞后先自动重建再开跑；重建动作从 merge-back 单点（dist_conflicts.py `_rebuild_dist_after_merge`）扩散到 serving 层；重建失败不静默继续，按环境性失联路径升级。

## Capabilities

### New Capabilities

- `verdict-env-exemption-handshake`: 裁决 env 豁免与 admin 升级链的握手——豁免清单非空时阻断直接 verified，强制走补救+重验+admin 咨询链
- `serving-dist-freshness-probe`: verify run 前 serving 层的 dist 新鲜度探针与自动重建

### Modified Capabilities

- `verify-environment-sanity-gate`（归档 2026-09-02-improve-scheduling-noise-governance）：inconclusive 判据从「全批 blocked-env」扩展到「裁决后全部环境性」的混合形态

## Impact

- `core/pm_engine/verification/escalation.py`：混合形态判据扩展
- `core/pm_engine/verification/pipeline.py`：judge 采纳尾段接豁免握手（阶段 2.6 之后、全绿快道与 judge 采纳之间的新拦截点）
- `core/pm_engine/verification/serving.py`：run 前 dist 探针 + 自动重建
- 既有回归约束：不误伤既有 inconclusive 链（全批 blocked-env 语义不变）、不影响全绿机械快道（0 失败 0 警告无豁免对象）、重验通道不烧 repeated_failures 信号预算的既有语义保持
