# 验证报告：evo-add-impl-run-budget-sizing

> ⚠️ 本报告由框架于 2026-10-02T21:12:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T21:12:40.146560+00:00+run-result@mtime1790975560259905206

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.68M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sizing-config-unit-tests | 4.1 归一化与推算边界单测（pytest 分组一）：tests/test_impl_run_budget_sizing.py 的 TestTurnBudgetSizingConfig（9 例：空/None/非 dict agents 段/非 dict sizing 段全缺省、非法类型与越界逐项回退、int 键 bool/float/越界拒绝、ratio 边界与 float 收敛、合法值直通、非 dict kill_early 段缺省）与 TestSuggestedTurnCapForScale（6 例：scale 等于阈值不抬、超阈抬升、suggested 小于 base 取 base、disabled 返回 base、非 int scale 拒绝、非 dict cfg 按缺省）。-v 形态逐条断言 PASSED 行（无 -q 覆盖；本文件无 parametrize，用例名无后缀）。出处：core/fast_track_result.py:376 get_turn_budget_sizing_config、:448 suggested_turn_cap_for_scale。 | pass | 0/12 | - |
| sizing-assembly-unit-tests | 1.2 装配级 sizing 单测（pytest 分组二）：TestImplTurnBudgetAssembly（7 例：大规模 spec 生效上限 800 且快照 50 未勾、小规模维持 base、STATE override 1200 优先于推算、estimate 异常 WARNING 回退 base、tasks.md 缺失不阻断派发、sizing 关闭大规模也维持 base、spec-review/dispute-judge/None 车道不参与推算且不取快照）。出处：core/agent_runner/runner.py:6058 _impl_turn_budget、:6008 _impl_turn_cap_override。 | pass | 0/9 | - |
| sizing-observation-unit-tests | 2.1/2.2 观测面与事件环单测（pytest 分组三）：TestTurnLimitActionObservation（5 例：extend/kill 两分支 evidence 均含 remaining_tasks、tasks.md 缺失记 unavailable 不误判、簿记占比 0.9 超阈只注记不改判且 WARNING 在场、占比 0.3 不注记）与 TestTurnExtensionEventLoop（2 例：fake Popen 驱动真实 _run_claude 轮询环，turn_extension 事件落盘含 remaining_tasks 且既有字段不丢、run_metrics 行同键在场；tasks.md 缺失时事件 remaining_tasks=None、evidence 注 unavailable）。出处：core/agent_runner/runner.py:2228 _turn_limit_action、:5497 事件落盘、:5637 run_metrics。 | pass | 0/9 | - |
| sizing-kill-early-unit-tests | 3.1 末位扩容拆停守卫单测（pytest 分组四）：TestKillEarlyGuard（8 例：关闭时同输入同输出逐位一致、开启且末次扩容+剩余超阈+进度近零提前 kill、剩余低于阈值不判、非末次扩容不判、进度健康仍 extend、评审/裁决车道 agent_type 不触发、无启动基线保守跳过、封顶语义优先于守卫）。出处：core/agent_runner/runner.py:2451 _turn_kill_early_evidence。 | pass | 0/10 | - |
| sizing-config-pure-probe | 独立探针（不依赖单测夹具，输入取值区别于单测）：直接调用 core/fast_track_result.py 的 get_turn_budget_sizing_config 与 suggested_turn_cap_for_scale，以 JSON 输出核对——全缺省七键（enabled=True/45/800/0.5/kill_early False/10/0.1）、None config 与垃圾值 config（enabled='yes'/threshold=0/suggested=-5/share=1.5/ke.enabled=1/remaining='x'/floor=2.0）逐项回退后与缺省全等、ratio 整数 1 与 0 的 [0,1] 域接受、scale=45 等于阈值不抬（严格大于语义）、scale=46 抬到 800、base=900 时大规模仍取 900（只抬不压）、enabled=False 与字符串/浮点 scale 恒返回 base。出处：core/fast_track_result.py:376-476。 | pass | 0/18 | - |
| sizing-assembly-probe | 独立探针（1.2 装配行为复核，tests.helpers.make_runner 最小装配 + 自建夹具，输入区别于单测）：agents.max_turns=400 下——50 未勾任务 spec（scale 50>45）生效 800 且快照 50 未勾；3 任务小 spec 维持 400；spec-review/dispute-judge/None 车道维持 400 且无快照；ghost 缺 tasks.md 维持 400 不抛异常；sizing.enabled=False 维持 400；STATE impl_turn_cap_override=1200 优先生效 1200；suggested=500 低于 base=700 时大规模取 700（只抬不压）。出处：core/agent_runner/runner.py:6058 _impl_turn_budget、core/fast_track_result.py:152 estimate_spec_scale。 | pass | 0/11 | - |
| turn-limit-observation-probe | 独立探针（2.1/2.2 判定面复核，自建 run 文件与 tool_result 流量事件，输入区别于单测）：20 未勾任务 spec 下——extend 分支 extension_index=1/new_turn_cap=500（step 100）/remaining_tasks=20/evidence 同时含 remaining_tasks=20 与流量文案；kill 分支（空 run 文件无活性）remaining_tasks=20 且 evidence 含 no liveness 与 remaining_tasks=20；spec_name=None 时 remaining 为 None 且 evidence 注 unavailable；簿记占比 0.9≥0.5 时仍 extend、evidence 注 bookkeeping_share=0.90>=0.50、WARNING 在场；占比 0.3 不注记。出处：core/agent_runner/runner.py:2228-2449。 | pass | 0/19 | - |
| kill-early-guard-probe | 独立探针（3.1 守卫复核，输入区别于单测）：kill_early.enabled=true 时——末次扩容（used=1，TURN_EXTENSION_MAX=2）+剩余 25≥10+进度 0/25=0≤0.1 → kill 且 evidence 含 early-split: last extension (2/2)、remaining_tasks=25 与 run progress 0.00 <= 0.1；同样输入在缺省关闭（无 sizing 键）下逐位回退为 extend（关闭零行为变化）；同输入 agent_type=spec-review → extend 不触发（评审车道豁免）；无启动快照 → extend 保守跳过；剩余 5<10 → extend；used=0 非末次 → extend；进度健康（5/20=0.25>0.1）→ extend；封顶 used=2 → 无条件 kill 且 evidence 为 budget exhausted 文案（封顶优先于守卫）。出处：core/agent_runner/runner.py:2451-2512。 | pass | 0/21 | - |
| turn-extension-event-e2e-probe | 独立探针（轮询环端到端，fake Popen 驱动真实 _run_claude，输入区别于单测）：max_turns=4（step=1）、3 未勾任务 spec——assistant 事件触发两次续期判定后封顶 kill（RuntimeError Max turns）；落盘 run 文件中 2 条 turn_extension 事件均含 remaining_tasks=3、evidence 含 remaining_tasks=3、extension=1/2、turn_step=1、new_turn_cap=5（既有字段不丢）；run_metrics 末行 remaining_tasks=3；ghost 无 tasks.md 变体事件 remaining_tasks=None 且 evidence 注 unavailable。出处：core/agent_runner/runner.py:5490-5512 事件落盘、:5637-5692 run_metrics。 | pass | 0/16 | - |
| state-override-roundtrip-probe | 独立探针（STATE 覆写键全链路）：core/state_machine.py 的 IMPL_TURN_CAP_OVERRIDE_FIELD 写 1200 → 新实例从盘重读仍为 int 1200（update_spec 写入端 int 显式转换防字符串往返）；STATE.md 文本含 - impl_turn_cap_override: 1200 行（序列化白名单在场）；runner 消费点 _impl_turn_budget 生效 1200；duck-type STATE 桩注入数字字符串 '1350' → 读侧 isdigit 容错取 1350、布尔 True、负数 -5、缺字段 → 一律等价 override=None（不放大为 run 故障）。出处：core/state_machine.py:225/:522-529/:653-665、core/agent_runner/runner.py:6008-6033。 | pass | 0/9 | - |
| adr103-knowledge-note-probe | 5.1 knowledge 注记在场景：spec/knowledge/adr/ADR-103-turn-limit-liveness-renewal-forced-kill-wip-salvage.md 含观测字段注记（remaining_tasks 于 turn_extension/run_metrics、TaskCreate+TaskUpdate 簿记占比观测）、STATE 覆写键 impl_turn_cap_override 与 suggested_turn_cap_for_scale 推算、kill_early 守卫（缺省关闭、仅实现车道、复用 WIP 保全、TURN_EXTENSION_MAX 末位条件）与 ADR-103 续期矩阵的关系表述——file_content 三条 + python 探针核对中文语义关键词。出处：tasks.md 5.1、ADR-103 文件 :26-28。 | pass | 0/15 | - |
| adjacent-regression-suite | 回归哨：与本 SPEC 改动面相邻的三套既有套件合跑（tests/test_turn_limit_lifecycle.py + tests/test_fast_track_result.py + tests/test_agent_runner.py，50 例）——轮次上限生命周期、fast_track_result（estimate_spec_scale/scale_precheck 同文件邻接）、agent_runner 主体行为零回归。-q 安静形态（无 -v 并列），断言 exit_code 与 50 passed 汇总行。 | pass | 0/2 | - |
