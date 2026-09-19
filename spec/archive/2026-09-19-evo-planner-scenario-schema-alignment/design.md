# 设计：场景断言 schema 单源化与写前预校验

## Context

2026-09-13 两批次 100% 剔除（fenixd.log 6884/6958）：planner 生成 25 条 scale-estimate-*（output_match 缺 expected）与 17 条 blind-run-marker-*（json_output 缺 step）全部被写端校验拒绝，触发退回 plan+重跑 planner（1789282524）。校验规则在 core/verify_engine/scenarios.py:585-600，planner 指令在 agents/planner-plan.md:94-96 仅列类型名——两处分裂，LLM 只能猜结构。17650012 修了读侧迁移，写侧未动。

## Goals / Non-Goals

- **Goals**：生成侧产出的断言结构满足写端校验；非法条目写前逐条剔除，避免整批重跑。
- **Non-Goals**：不改校验规则本身（拒绝语义保留）；不做场景运行时执行器的改动；不引入外部 schema 文件（单源锚定在 scenarios.py）。

## Decisions

### D1：单源锚定在 core/verify_engine/scenarios.py 派生

**选择**：把必填字段规则收敛为 scenarios.py 中可被引用的权威结构（如 REQUIRED_FIELDS 常量或从现有校验分支抽函数），planner prompt 的渲染侧读取该结构生成字段说明。

**理由**：该校验器已是词表权威源（planner-plan.md 自注『以代码为准』），扩展为字段级权威源零范式切换；校验与生成自然同源。

### D2：prompt 注入与写前客户端预校验双保险

**选择**：planner-plan.md 内联必填字段与样例（降低生成侧错误率）+ 写盘前客户端预校验逐条剔除（兜底拦截，防单条毒化整批）。

**理由**：前者治本（LLM 少犯错），后者治标（错误不扩散）；两者成本都低，共用同一单源规则。

**边界（既有实现缺口）**：写端门（verification.py:1226-1252，fix-frozen-scenario-orphan-reservoir 2.2/2.4）已做逐条剔除与 >20% ERROR 升级，但只记账、不改 planner 写的 test_scenarios.json，非法条目仍在 → 阶段2 load_scenarios（verification.py:1809）失败 → 退回重排。兜底须使剔除作用于阶段2 加载的场景集（写回合法子集或加载侧逐条容错），并注意冻结场景守卫（verification.py:1562-1581）与 scenarios.json 持久化集的一致性。

**空集信号（评审补充）**：写回合法子集后「全部条目非法」不再是加载报错（该报错正是本方案消除的那条），而 `_apply_scenario_freeze` 的三处调用点（verification.py:1732 / 2359-2364 / 4673-4678）except 均只记 WARNING 后继续——异常通道传不出信号。故空集判定以该函数的结构化返回值承载（`{"aborted": "no_valid_scenarios", ...}`），且须先于 `save_scenario_set`（verification.py:1255）短路，避免把空集写进 scenarios.json（load_scenario_set 对 `scenarios: []` 返回非 None，core/verify_scenarios.py:153-189，会让下一轮 diff 从首轮口径退化为增量口径）。

**剔除的第二遍（评审补充）**：过滤后经补齐写回再剔除一批（verification.py:1333-1354，含从备份取回的既有场景），该批现仅 WARNING；>20% 升级口径须以写回前最终合法集为基准统计。剔除改变了 test_scenarios.json 与持久化集，紧随其后的交互契约覆盖校验（verification.py:1744-1753）会把被剔除场景读成覆盖缺口 → 退回重排，故剔除 id 须可被覆盖校验识别、与「设计漏项」区分。

### D3：预校验复用写端校验函数

**选择**：写盘前调用与写端相同的 validate_scenario（scenarios.py），逐条报告。

**理由**：保证预检与终检同口径，杜绝『预检过了终检失败』的二次分裂。

### D4：生成侧覆盖两条分支（评审补充）

**选择**：schema 注入段做成单一动态段函数，planner-plan（prompt_builder.py:244-248）与 fast-track（prompt_builder.py:277-292）两分支共用；agents/fast-track.md 的内联 schema/枚举（agents/fast-track.md:78-98）收敛为指向注入段的最小说明。

**理由**：fast-track 的 PHASE 2 自行生成并写入 test_scenarios.json（agents/fast-track.md:11-12），是第二个生成侧，且其产出不过写端门（fast-track 硬门 validate_fast_track_result 只比对场景 id，verdict_check.py:1064-1130），残留漂移只在后续 full 模式冻结复用时报「冻结文件验收失败」升级 admin（verification.py:1562-1581、3261-3267）。只改 planner-plan 分支等于把同类缺陷留在另一条车道上。

**第三条写入车道（评审补充）**：上条「另一条车道」的判据同样适用于 **judge 原地修复通道**——agents/planner-judge.md:147 明确要求 judge「直接修改 {scenarios_path}：补自建夹具/种子场景、修正客观错误步骤与断言、补 depends_on 串接」，即 judge 会**重写断言结构**；而 planner-judge 分支（prompt_builder.py:249-276）不在 2.1 注入范围内，judge 只能凭同源知识猜必填字段，与本次事故的生成侧漂移同型。故 2.1 的注入 MUST 同样挂载到 planner-judge 分支（写入后经 verification.py:2359 的冻结门剔除，故暴露面比 fast-track 小，但漂移源相同、且剔除可能触发 3.7 的空集拒绝重入）。

**admin 修复通道边界（评审补充，明示不进注入范围）**：administrator 亦会写 test_scenarios.json（prompt_builder.py:295-299、309-329），但其约束段已**机械告知**「写回必过 validate_scenario_dicts 门，被拒时按框架回传的逐条错误清单重修」——即 admin 走「门 + 错误清单」闭环自纠，不依赖先验 schema 知识（区别于生成侧的一次性盲写）。故 admin 车道**不注入** schema 段，此边界为有意选择，非遗漏；实现时无须改动 admin 分支。