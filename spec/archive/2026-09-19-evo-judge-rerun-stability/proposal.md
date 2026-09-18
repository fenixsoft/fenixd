# judge-rerun-stability — 验证裁决稳定性：judge 重跑上限与 verified 一次性放行

## 背景
add-web-ui 单 spec 在 09-10~09-11 窗口内累计 11 次 planner-judge + 2 次 verify + 4 次 admin 处置 run 相互踩踏，_tokens_in 从 79.75M 增至 95.72M（+15.97M / +$24.6），而验证最终早已通过（32 场景 28 通过 4 失败 = 0 product bug，后 verified 31 pass + 1 warning）。多轮 run 均为验证基础设施误判买单：同一 spec 的 judge 反复重跑、legacy/planner 各自独立裁决，验证已通过却反复空转。

## 目标
- 对同一 spec 的 judge 重跑设上限：verdict 连续稳定（两次一致）即复用上次结果，不重跑。
- report.json 判定 verified（或等价的终态裁决）后一次性放行，不允许 legacy/planner 各自独立误判覆盖已验证结论。
- 空转 run 数量与 token 成本可观测（STATE.md 记账）。

## 非目标
- 不改验证结果文件读取路径（另见 verifier-result-single-source）。
- 不涉及预算/升级闸门的费控语义分层（另见 infra-failure-budget-exempt）。

## 验收
- 同一 spec 连续两轮 judge verdict 一致时不产生第三轮 judge run。
- verified 裁决落盘后，后续 legacy/planner 判定不得将该 spec 覆盖为 blocked/bug-found。
- STATE.md 对 add-web-ui 类场景记录 judge 重跑次数与 token 增量。