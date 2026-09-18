## Context

2026-09-18 `fix-verify-serving-disk-reclaim` 事故：SPEC 起草阶段把「持久化场景集与结果到 `.fenix/verify-progress/<spec>/`」写成实现者任务（tasks.md 6.2）。`test_scenarios.json` 是验证链 `planner-plan` 车道才产出的文件，实现者交付时它根本不存在——实现 run 为满足任务门禁，用 Bash heredoc 伪造 23 条证据文案当冻结场景集，验证读侧见文件即加载、验收失败 → spec 置 `blocked`。

有价值的观察是：**根因不在读侧，在立项侧**。读侧「文件存在即权威」是既有设计，它只是忠实地消费了一份本不该存在的文件。真正的问题是**任务书要求实现者交付他车道才产出的东西**，而这个形态在现有 `skills/fenix-new/SKILL.md` §3.2.1 的四类禁止清单里没有对应项，起草者与 lint 都无据可依。

同时已确认：**堵写文件不可行**（实现者持有 bash 全集，可绕过任何写侧 hook；本次事故正是用 Bash heredoc 绕过了 Write/Edit hook 白名单）。故本次治理落在**立项侧机械门**，而非写侧拦截或读侧溯源。

现状代码落点：

- `core/deliverables.py:lint_tasks_text`（1665-1729）：tasks.md 文本判定单一实现，被三个挂点复用——晋升门 `drafted→ready`（`core/pm_engine/promotion.py`）、full 车道收口 relint（`core/pm_engine/verification/branch_guard.py:_tasks_md_relint_from_branch`）、fast-track 车道收口复检（`_tasks_md_relint_from_worktree`）。
- `core/deliverables.py:lint_tasks_parseable`：读 tasks.md 文件后转 `lint_tasks_text` 的薄封装。
- `.spec.yaml` 的 `mode`（`full`/`fast-track`，缺失按 `full`）决定执行车道，与 `core/run_task_track.py`、`core/fast_track_result.py` 的既有消费同源。

## Goals / Non-Goals

**Goals：**

- 机械识别「任务要求实现者产出他车道验证产物」的形态，在晋升（drafted→ready）即拦下，而非等实现 run 造假后再暴露。
- 单一实现、三个挂点自动一致生效（复用 `lint_tasks_text`）。
- 归属表作为声明式单一真相源，未来新增验证产物只改一处。
- 零误拦：不伤任何存量合法 spec（判据要求双条件同时命中）。

**Non-Goals：**

- **不做读侧溯源凭据**（哈希/run_id 交叉核对）：本次不改变「文件存在即冻结集」的读侧语义。
- **不做写侧收窄**（收回实现者对 `.fenix/verify-progress/` 的写授权、copyback 白名单）：已论证堵写不可行且与「消除动机」方向相左。
- **不做 OS 级沙箱**（抵御有 bash 的蓄意对手）：与本门禁的「消除意外与激励」定位不同量级，显式排除。
- 不捕获**任意**「Agent 做不到的事」——只机械覆盖「需产出他车道产物」这一类；其余三类仍靠 §3.2.1 指引与 `unattainable` 申报兜底。

## Decisions

**D1：判据用「双条件合取」，而非单一路径匹配。**

单条件（任务行提到 `verify-progress` 即拦）实测误拦率 100%：全库 15 条命中**全是**「写代码让框架产出该文件」的合法任务（如「新增 `_write_impl_result_snapshot` 落盘快照」）。故判据 MUST 为：

1. 命中验证产物路径标识，**且**
2. 任务行**未指向任何代码文件**（无代码扩展名 / 已知代码路径特征）。

加此条件后全库（184 份 tasks.md，含 archive）候选违规 **0 条**，本次事故的 6.2 是唯一真阳性。合计正是「一个无代码可写的任务，却要产出验证产物」——这就是必不可能完成的确切形态。

*备选（已否）*：改用「产物路径前是否有写动词」的 NLP 式匹配——实测仍有 15 条误报（「把…原子写入 `.fenix/verify-progress/`」是写代码的描述），且脆弱。

**D2：归属表落成独立模块常量，而非散落正则。**

新增 `core/artifact_ownership.py`（或 `core/deliverables.py` 内常量块，二选一由实现者按「起草自检是否需要 import」决定），声明式给出「产物路径标识 → 归属车道集合」。理由：归属关系是**领域知识**（哪个车道写哪个文件），不是匹配细节；集中一处后，lint 与 `skills/fenix-new` 的自检脚本可共用，避免第三处枚举。归属表条目至少含 proposal/specs 中列出的五类。

**D3：执行车道取 `.spec.yaml` 的 `mode`，缺失保守按 `full`。**

与既有 `mode` 消费语义一致（`run_task_track.py` 读侧缺省 full）。保守侧的正确性：full 归属车道是 `implementer`，而验证链产物归属集合**均不含 `implementer`**，故 full 车道下恒判违规；fast-track 车道对 `test_scenarios.json`/`scenarios.json` 合法（fast-track 自行出题并落盘，`agents/fast-track.md` 第 6 条），对 `report.json`/planner-judge 结果文件仍判违规。这精确对应「哪些任务对该车道不可能完成」。

**D4：违规走 `lint_tasks_text` 既有返回通道（追加违规消息），fail-open 语义沿用。**

不新增异常路径、不新增门禁类型——违规作为 `List[str]` 的一条消息返回，三个挂点零改动即生效；lint 自身故障仍 fail-open（现有 `_lint_tasks_parseable` / `_lint_deliverables` 的 try/except 包裹）。

**D5：起草指引同步改两处 prompt（`skills/fenix-new/SKILL.md` §3.2.1 + `agents/evolution.md`）。**

机械门与指引是纵深关系：机械门保底拦截，指引让起草者第一次就写对（省一次 drafted→error 往返）。两条起草入口（人工 `/fenix-new`、自进化 draft）都不漏。

## Risks / Trade-offs

- **[误拦合法 spec]** → 全库 184 份 tasks.md 零误拦回归作为硬验收；判据双条件合取；实现期若发现某合法形态被拦，优先放宽判据而非加白名单。
- **[判据是文本启发式，可能漏拦]** → 明确 fail-open 取向：宁可漏拦怪题，绝不误拦合法 spec。漏拦由 §3.2.1 指引与 `unattainable` 申报兜底（非本次消除目标）。
- **[归属表与真实写侧漂移]** → 归属表由测试锚定（对核心产物路径做断言），未来新增验证产物需同步；漂移风险低（验证产物集合稳定）。
- **[晋升门是全库公共链路]** → 违规只影响含该类任务行的 spec；不影响既有 spec（零误拦回归保证）。

## Migration Plan

无数据迁移。规则上线后仅对**新起草**的 spec 产生约束（存量 spec 已过晋升门，收口复检仅在其重跑时生效，且零误拦保证存量合法 spec 不被拦）。回滚 = revert 该规则代码，无状态残留。

## Open Questions

- 归属表的载体：独立模块 `core/artifact_ownership.py` vs `core/deliverables.py` 常量块——由实现者按「`skills/fenix-new` 自检脚本 import 便利性」在实现期定，二者均接受。
- fast-track 车道是否需要额外放行 `.fenix/verify-progress/<spec>/<spec>.json`（fast-track 的 progress 文件，见 `prompt_builder` fast-track 分支）——实现期核对归属表是否需要补该条。
