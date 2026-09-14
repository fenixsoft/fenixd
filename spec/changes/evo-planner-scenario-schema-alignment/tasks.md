## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_planner_scenario_schema_alignment.py
  kind: new
```

## 1. 断言字段规则单源化

- [x] 1.1 core/verify_engine/scenarios.py：把断言必填字段规则（output_match/file_content 需 expected、json_output 需 step+path 等）收敛为可引用的权威常量/函数（供校验与生成侧共用）
- [x] 1.2 写端校验改读该单源（行为零变化回归）

## 2. planner 指令注入

- [x] 2.1 core/agent_runner/prompt_builder.py：新增「断言/操作 schema 段」动态段函数（与既有动态段同机制），并注入**两个场景生成分支**——planner-plan（挂载点 prompt_builder.py:244-248）与 fast-track（prompt_builder.py:277-292）。fast-track 的 PHASE 2 同样直接写 test_scenarios.json（agents/fast-track.md:11-12），是第二个生成侧，只注 planner-plan 分歧会留下同一类漂移（该车道的非法条目不在写端门覆盖范围内，只在后续 full 模式冻结复用时报「冻结场景文件验收失败」，verification.py:1562-1581）。运行时从 core/verify_engine/scenarios.py 的单源结构渲染各 cli/api 断言类型的必填字段说明与合法 JSON 样例（output_match 含 expected、json_output 含 step+path），并同时覆盖各 kind 操作的必填字段（cli `run` 的 command、api `http_request` 的 method/url，写端 _validate_cli/_validate_api 校验）
- [x] 2.2 agents/planner-plan.md：仅保留指向该注入段的最小说明，MUST NOT 手写第二份必填字段枚举——该文件与代码规则手工脱节即本次事故成因（agents/planner-plan.md:94-96 只列类型名），且该文件第 89 行自注「不要在本文件维护完整可漂移枚举」。注意第 93-95 行摘要同时含**操作**必填字段说明（run 的 command、http_request 的 method/url），删除须确认其已由 2.1 注入段承载，不得随摘要一并丢失而成新漂移源
- [x] 2.3 agents/fast-track.md：PHASE 2「场景 JSON schema」段（agents/fast-track.md:78-98）内联的 schema 样例与 web 断言/操作枚举，是对单源的**第二份手写枚举**，MUST 改为指向 2.1 注入段的最小说明（其中「多形态验证见 agents/planner-plan.md」的既有指向语句可保留，但 2.2 改完后该处须同步指向注入段）；漏改则 fast-track 车道继续漂移
- [x] 2.4 第三条写入车道（评审补充）：**judge 原地修复通道同样重写断言结构**——agents/planner-judge.md:147 要求 judge「直接修改 {scenarios_path}：…修正客观错误步骤与断言…」，而 planner-judge 分支（prompt_builder.py:249-276）不在 2.1 注入范围内，judge 只能猜必填字段（与本次事故生成侧漂移同型，同一「另一条车道」判据）。故 2.1 的注入段 MUST 同样挂载到 planner-judge 分支（挂在既有动态段链上，与 `_scenario_static_findings_section` 等同机制）；**admin 修复通道不进注入范围**（prompt_builder.py:295-299、309-329 已机械告知「写回必过 validate_scenario_dicts 门 + 按回传错误清单重修」，属门+错误清单自纠闭环，非生成侧盲写）——此边界须在实现中显式保持，不得顺手给 admin 也加注入段

## 3. 写前客户端预校验

- [x] 3.1 core/pm_engine/verification.py：planner 产出经与写端一致的校验器（validate_scenario_dicts，与读端同源且内含旧 schema 迁移）逐条预检，非法条目剔除留痕（场景 id + 缺失字段），合法条目照常进入执行
- [x] 3.2 剔除必须生效于阶段2 实际加载的场景集：既有实现（verification.py:1226-1252，fix-frozen-scenario-orphan-reservoir 2.2/2.4）只做逐条记账、不改 planner 写的 test_scenarios.json，非法条目仍在 → 阶段2 load_scenarios（verification.py:1809）抛「场景文件包含 N 个错误」→ env_error → 退回重排（09-13 06:55:24 / 07:08:13 实证）。**选定方案：写回合法子集**——阶段1 冻结处理时用过滤后的合法集整体重写 test_scenarios.json（与 verification.py:1355-1364 补齐写回同型，经 prepare_scenarios_for_write）。MUST NOT 选「加载侧逐条容错」：load_scenarios（core/verify_engine/scenarios.py:770-780）把结构非法判为整文件 ValueError，_load_frozen_scenarios（verification.py:3261-3263）依此判「冻结文件损坏」以保「场景一经冻结绝不静默重出题」语义，读侧容错会击穿该语义，且读侧刚由 frozen-scenario-schema-migration 加固，不宜再改。**写回点位置约束**：MUST NOT 让合法子集写回覆盖补齐写回结果——verification.py:1296-1364 的补齐分支（另一条 test_scenarios.json 写点）写的是「过滤后 planner 产出 + _scenarios_full.json 取回定义」的并集，若被合法子集整体覆盖，备份取回的既有场景再次丢失（回归面丢失，fix-frozen-scenario-orphan-reservoir 3.2 已修模式复活）；做法：合法子集写回与补齐写回互斥（补齐分支已写即不再写）或收口为单次写回，且两处写回内容均须为过滤后集合。**主路径写回（MUST，否则修复对本次事故空转）**：合法子集写回 MUST 在补齐分支之外的**主路径**执行——事故实证条件（第 1 轮、persisted 为空、无理由缺失 0；.fenix/logs/fenixd.log:6890「场景集冻结…无理由缺失 0」）永不进入 verification.py:1296 的补齐分支，而该分支内的 verification.py:1358 是 _apply_scenario_freeze 当前唯一的 test_scenarios.json 写点（全函数 grep 无第二处）；若实现仅把写回挂在补齐分支上，非法条目仍留在文件中、阶段2 仍旧整轮失败，本修复对事故完全无效。故 MUST 在过滤得合法集并完成空集判定（3.5/3.8）后，于主路径写入过滤后合法集，覆盖首轮/无缺失轮
- [x] 3.3 顺序与一致性：写回合法子集后 scenarios.json 持久化集 MUST 同源过滤，否则两文件分裂——diff_planner_output（core/verify_scenarios.py:414-430，首轮全量采用 planner 产出、不按 schema 过滤）会保留被剔除场景的 id，而 test_scenarios.json 已是合法子集；此后走非冻结复用路径时，diff 以持久化集为基准会把非法 id 判为「无理由缺失」触发补齐扰动。做法：_apply_scenario_freeze 内先按 validate_scenario_dicts 过滤 planner_scenarios（即复用现有 valid_planner）再调用 diff_planner_output，使 scenario_set 与写回文件同源；**移除声明豁免（评审补充）**：3.3 的「先过滤再 diff」不得把 planner 的**移除声明**一并滤掉——`_parse_reasons`（core/verify_scenarios.py:353-366）只认「带 id 的条目 + `remove_reason`」，而纯移除声明条目（如仅 `{id, remove_reason}`，kind 缺省 web）过不了 `validate_scenario_dicts`（会被判「缺少 navigate 步骤」，scenarios.py:526-531），若随之从 diff 输入中被滤除，`reasons` 丢失该 id → 既有场景被判 `unreasoned_missing` → 触发补齐分支从 `_scenarios_full.json` 取回，**planner 的显式移除被静默反转为保留**（且 diff.ok 语义翻转）。故过滤 MUST 保留携带 `remove_reason` 的声明条目（或令 diff 仍看到移除声明、仅对「实际写入集」过滤），使移除理由照常生效；并确认过滤后写回的文件必过 load_scenarios 验收，不触发冻结场景守卫（verification.py:1562-1581 把非法 test_scenarios.json 判为「冻结文件验收失败」→ admin 升级）
- [x] 3.4 回归断言：剔除数超本轮 20% 时 ERROR 升级（既有语义，非退回触发器）保留；阶段2 加载不再因个别非法条目整轮失败退回
- [x] 3.5 空集显式兜底（MUST NOT 依赖加载报错）：写回合法子集后，「全部条目非法」**不再触发阶段2 load_scenarios 报错**——既有退回路径（verification.py:1809-1811 捕 ValueError → env_error → 退回 plan 重排，09-13 06:55:24 实证 .fenix/logs/fenixd.log:6889）恰是本方案写回所消除的那条错误。故 MUST 在写回处显式判定：过滤后合法集为空 → 不写空文件、不进阶段2，直接按验收失败退回 plan 重排并 ERROR 升级留痕。**后果实证（不修则白洗）**：0 场景经 engine.run([]) 产出 total=0/passed=0/failed=0 且**无 env_error** 的报告（core/verify_engine/engine.py:115-231），全绿快道因 passed<=0 返回 None（verification.py:3574-3580）→ 落常规 judge，而洗白门对「无场景数据」fail-open 放行（verification.py:3300-3301）、空场景表亦判合规（core/verdict_check.py:221、266-268）→ 存在「0 覆盖判 verified」的洗白路径；且空文件下一轮被 _load_frozen_scenarios 判「冻结场景文件为空」（verification.py:3266-3267）升级 admin，验证卡滞
- [x] 3.6 写回失败可观测：写回成为本修复主路径，而 _apply_scenario_freeze 调用点外层 except 仅记 WARNING 后继续（verification.py:1731-1738）——写回异常会静默退化回「整批失败」老路径。写回相关异常 MUST 以 ERROR 留痕（含 spec 名与原因），不得只留 WARNING 旁证
- [x] 3.7 空集判定的传递接口（补 3.5）：`_apply_scenario_freeze` 有三处调用——阶段1 主路径（verification.py:1732）、judge 原地修复重入（verification.py:2359-2364）、改道重入（verification.py:4673-4678），且三处调用点的 except 均只记 WARNING 后继续，**异常通道传不出「空集」信号**（raised 会被吞、继续走到阶段2）。故 3.5 的空集判定 MUST 以该函数的**结构化返回值**承载（如 `{"aborted": "no_valid_scenarios", "rejected": [...]}`）并由调用点消费：阶段1 主路径置 replan_feedback 走既有退回（与 verification.py:1745-1753 交互契约退回同型，受 replan_left 预算约束）；两处 judge 重入路径 MUST 拒绝本次重入（保持原状并留痕），MUST NOT 以空集或未过滤文件继续进入阶段2。**重排预算耗尽分支（评审补充）**：上句「与 verification.py:1745-1753 同型」只覆盖 `replan_left > 0` 的退回分支，其后的 verification.py:1754-1758 是「预算耗尽 → ERROR 留痕继续验证」fall-through——对空集即等于携 0 场景落入阶段2，正是 3.5 明令 MUST NOT 的洗白路径。故空集判定在 `replan_left <= 0` 时 MUST NOT 落入该 fall-through，MUST 显式结束本轮（比照既有 env_error 退回的预算耗尽分支 verification.py:1929-1943：置 `implemented` + error 返回；或经 `_escalate_env_blocked` 升级），并留痕
- [x] 3.8 空集判定与写盘顺序（补 3.5）：空集判定 MUST 先于 `save_scenario_set`（verification.py:1255）与补齐写回短路返回——否则持久化集 scenarios.json 被写成空集，而 load_scenario_set 对 `scenarios: []` 返回**非 None**（core/verify_scenarios.py:153-189，`data.get("scenarios")` 为空列表时仍走 `ScenarioSet.from_dict` 返回对象），下一轮 diff 从「首轮全量采用 planner 产出」退化到增量口径，语义静默漂移。剔除后无合法场景时 MUST 保持既有持久化集不变
- [x] 3.9 剔除比例口径（补 3.4）：超本轮 20% 的 ERROR 升级 MUST 以**写回前最终合法集**为基准统计——既有实现只统计第一遍 rejected（verification.py:1226-1252）；本方案的合法子集写回使写入集经补齐 pass 再剔除一批（verification.py:1333-1354，含从 _scenarios_full.json 取回的既有场景），该批现仅 WARNING、无比例升级，静默缩小回归面。两遍剔除须合并统计，或第二遍同样独立升级留痕

- [x] 3.10 剔除留痕 → 覆盖校验消费（评审补充：把 4.5 中仅出现在「测试」段的实现 MUST 前置为独立实现任务）：`_apply_scenario_freeze` 剔除的条目 id/清单 MUST 以本轮可读形式留痕，并被紧随其后的 `_apply_interaction_contract`（verification.py:1388-1399，读同一 test_scenarios.json）识别，MUST NOT 让被剔除条目在覆盖校验处表现为无因「设计漏项」缺口（否则触发「重排-剔除」循环，见 4.5）。实现落点优先收在 verification.py 内（冻结处暂存本轮剔除集 + 覆盖校验处消费）；若实现确需修改 `core/interaction_contract.py`（`validate_interaction_coverage` 签名/入参），MUST 同步在 Deliverables 补该声明——否则修改越出声明范围，交付守卫会误判

## 4. 测试

- [x] 4.1 tests/test_planner_scenario_schema_alignment.py：生成侧样例与校验规则一致性（output_match/json_output 等合法样例通过写端校验）；注入段内容由 scenarios.py 单源派生（改常量 → 注入文本随之变化，MUST NOT 需手改 prompt 文件）
- [x] 4.2 单条非法剔除留痕；阶段2 加载不因个别非法条目整轮失败（回归）；无合法场景可执行时**显式**退回 plan 重排（断言 0 场景报告不进入裁决路径，见 3.5）；**重排预算耗尽（`replan_left <= 0`）时断言本轮显式结束、0 场景报告同样不进入裁决路径**（见 3.7 预算耗尽分支）
- [x] 4.3 单源化等价性回归（锁定 1.2「行为零变化」）：对各类必填字段（output_match/file_content 的 expected、json_output 的 step/path、status_code 的 expected、body_contains 的 expected、run 的 command、http_request 的 method/url 等）构造缺字段样例，断言仍被写端校验拒绝——注意既有校验的细节差异须原样保留（status_code 判 `expected in ("", None)`、body_contains 判 `not expected`，见 scenarios.py:640-655）；合法样例仍通过
- [x] 4.4 注入覆盖面回归（锁定 2.1/2.3/2.4）：planner-plan、fast-track、planner-judge 三个分支的 prompt MUST 均含由单源渲染的 schema 段；断言 agents/fast-track.md 内不再存在独立于单源的断言/操作枚举，且 administrator 分支**不含**该注入段（2.4 边界，防越界扩散）；改 scenarios.py 单源常量 → 三分支注入文本随之变化
- [x] 4.5 交互契约去噪回归（**新增回归面**）：剔除会改变 test_scenarios.json 与持久化集，而紧随其后的交互契约覆盖校验（verification.py:1744-1753 → _apply_interaction_contract，读同一场景文件，见 verification.py:1390-1397）会把「因 schema 非法被剔除」的场景判成**覆盖缺口** → 退回 plan 重排（预算内）→ planner 可能再生成同类非法场景，形成「重排-剔除」循环。被剔除条目 id MUST 落盘/留痕且可被覆盖校验识别（至少区分「设计漏项」与「条目非法剔除」两类缺口），MUST NOT 让剔除在覆盖校验处表现为无因缺口