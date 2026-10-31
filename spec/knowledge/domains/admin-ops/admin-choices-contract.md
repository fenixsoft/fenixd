# Administrator 处置与裁决注册表共用契约

<!-- knowledge: capability=admin-choices-contract rev=3
     sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/archive/2026-10-27-evo-recurring-stray-remediation,spec/archive/2026-10-31-fix-admin-choice-payload-and-scenario-pairing -->

Administrator agent 的自动处置与人工下拉选择收敛为同一裁决空间的契约（`agents/administrator.md` 处置输出段）。

## 规则

- Administrator 处置桶 2 信号时，先读取该 signal_type 在裁决选项注册表中的选项集；处置结论优先表达为 `choice_id` + 依据，写入处置记录的结构化字段。
- 仅当注册表无对应选项（处置超出既有裁决空间）时才允许自由处置，且必须在处置记录中回填「建议注册表新增选项」字段（含建议 id/label/action 语义），供自省通道消费。
- 框架消费处置记录时，`choice_id` 与人工下拉选择走同一执行路径：同一动作映射、同一留痕格式。
- `kind=SIGNAL` 类携带 choices 的记录（如 `build_artifact_paths_missing`，不进前端告警区）由本契约消费：Administrator 处置时按注册表选项表达结论。
- 复发型主树散件 MUST 当场根治（`agents/administrator.md` 铁律区条款）：处置 `maintree_stray_wip_stale` 告警时，evidence 带出「已 N 度处置」复发计数（N≥2，即同文件第 2 次处置起）即触发根治义务——MUST 当场执行根治（裁决选项 `untrack_stray_wip` 或等效手工操作）【或】在处置记录挂显式跟踪项（写明跟踪载体与复查时机），二者必有其一；MUST NOT 以「仅提交」第三次收尾——被 track 的生成物类散件每次构建必复发，仅提交只是把确定性复发挂起。首次处置（evidence 无复发计数）维持「提交+建议」现状，不强制根治。该义务以契约铁律承载而非代码硬拦截，代码侧保证根治路径一键可达与复发计数可见，违反义务由下轮告警与复盘回收。
- 处置记录支持结构化 `choice_payload` 键（字符串，内容为 JSON 载荷），是 Administrator 向裁决执行器传递动作载荷的唯一直传通道：`AdminDisposition` 携带该字段并随 final 记录透传落盘；自动执行调用执行器时 `note` 优先取 `choice_payload`——非空即整体直传，MUST NOT 经 `actions_taken` 文本拼接或长度截断；仅当载荷为空且所选选项非 payload 必需时，`note` 维持依据文本（`actions_taken` 截 200 字）。人工 alert-resolve 端点的 note 通道不受影响。
- 载荷必需选项缺载荷 fail-closed 硬门：处置记录 `choice_id` 指向注册表声明 `requires_payload` 的选项、而 `choice_payload` 缺失或为空时，该次处置判失败（success 折算 False），错误信息点名缺口（指出该选项需要 `choice_payload` JSON 载荷及契约形态），MUST NOT 折算为 resolved 类假收口；关联升级信号保持未处理（可重试裁决）。载荷在场但内容非法时由执行器既有载荷解析失败路径拒绝，不设第二道内容校验门。该硬门与执行通道的载荷前置判定互为冗余防线，任一生效即阻止「resolved 但执行必败」的假收口。
- 场景定义/夹具修订必走载荷路径：需修订场景定义或夹具供给层文件时，MUST 将修订后的完整场景集（及可选夹具文件）以 `choice_payload` JSON 载荷随 `choice_id=revise_scenario_reverify` 提交，由执行器白名单路径成对写回 `test_scenarios.json` 与 `_scenarios_full.json`（执行器语义见 [scenario-revision-reverify-exit](../verdict-adjudication/scenario-revision-reverify-exit.md)）；MUST NOT 绕开执行器直接编辑场景定义文件、全量备份或夹具供给层文件——单独手改单侧文件破坏成对一致，旧定义可经「无理由缺场景补齐」分支回填复辟。

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立 Administrator 处置优先消费注册表、choice_id 结构化表达、超出裁决空间回填建议的契约
- 2026-10-27 evo-recurring-stray-remediation（spec/archive/2026-10-27-evo-recurring-stray-remediation） — 契约新增复发型主树散件根治铁律：同文件第 2 度处置起 MUST 当场根治（untrack_stray_wip 或等效）或挂显式跟踪项、MUST NOT 仅提交第三次收尾，首次处置维持「提交+建议」不强制
- 2026-10-31 fix-admin-choice-payload-and-scenario-pairing（spec/archive/2026-10-31-fix-admin-choice-payload-and-scenario-pairing） — 契约新增 choice_payload 结构化载荷键（自动执行 note 载荷优先、不经 actions_taken 截断）、缺载荷 fail-closed 硬门（判失败点名缺口、不假收口、信号保持未处理）、场景/夹具修订必走载荷路径且禁止 out-of-band 手改（成对写回理由明文化）
