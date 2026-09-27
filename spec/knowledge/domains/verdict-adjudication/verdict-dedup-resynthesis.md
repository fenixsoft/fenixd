<!-- knowledge: capability=verdict-dedup-resynthesis rev=1 sources=spec/archive/2026-09-17-fix-verdict-dedup-resynthesis -->

# 裁决去重与重合成

批量归因查重的误伤降级与拒后闭环：拒绝后走定向重合成回路而非静默自锁，单根因级联失败合法放行。

## 现行规则

- 查重拒绝后的重合成回路：框架对批量归因查重（`batch_attribution_dedup`）拒绝的裁决报告，执行「落盘违规清单 → 派发定向重合成 judge run → 回灌同一校验入口」闭环，不保持 testing 静默等待。违规清单经 `verdict_violations.json` 通道落盘（与既有裁决校验违规同源），重合成 prompt 经 `_verdict_rejection_section` 注入定向修复纪律。
- 重合成范围限定：重合成 run 只重写被拒场景的归因文本字段（`first_failed_step` / 断言 triage evidence），不重做调查、复现或改写判定与未拒绝场景的任何字段；产物回灌完整校验链（`load_report` → `validate_report` → 查重门）后按既有语义推进或拒绝。
- 连续两次查重拒绝升级人工：重合成产物再次被查重门拒绝（连续 2 次）时，spec 置 blocked、error 携带两轮违规摘要、发送 admin 升级告警；不无限重试重合成。
- 重合成定向指令注入：查重拒绝时写入重合成指令文件（含被拒场景清单、逐场景现有归因文本、归因契约要求），并为每个被拒场景附失败步骤序号、断言 label 等框架已掌握的场景局部数据作差异化素材；重合成 prompt 契约为「归因文本 MUST 引用本场景局部数据（步骤序号/断言 label/完整 error），MUST NOT 套用共享模板串」。
- judge 归因文本契约（事前预防）：planner-judge prompt 声明——根因与 classification 允许多场景共享，但 `first_failed_step` 与断言 triage evidence MUST 引用本场景自己的步骤序号、断言 label 或完整 error（禁截断致多场景同文、禁模板串）。
- 查重归一化细分与级联豁免：`check_batch_attribution_dedup` 的归一化纳入场景局部数据（失败步骤序号、断言 label）；场景组 classification 相同、归因描述体共享同一根因短语、但失败步骤序号或断言清单逐场景不同时不计入查重命中（单根因级联失败的合法形态）；纯模板偷懒形态（连步骤引用都逐字复制）仍被拒绝。
- 原地重试派发前状态复查：agent_runner 的两处原地重试通道（provider-transient 退避、artifact-gate 退避）重派前复查 spec 状态——当前 status 非该 agent 预期态（judge→testing、implementer→implementing）或 frozen / `_cancelled_hold` 时放弃重试并返回语义化失败；检查自身异常时 fail-open（保持既有重试语义）。
- 拒绝语义文案：查重拒绝相关日志与注释使用「拒绝采纳」语义（report.json 已在盘上，拒绝的是状态机采纳），代码注释与实际重合成回路一致。

## 溯源

- 2026-09-17 fix-verdict-dedup-resynthesis — 确立查重拒后违规清单落盘+定向重合成+回灌校验闭环、二次拒绝升级 admin、归因文本事前契约、级联豁免归一化、原地重试前状态复查与「拒绝采纳」文案
