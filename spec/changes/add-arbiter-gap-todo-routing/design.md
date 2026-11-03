## Context

arbiter 立项通道（`core/pm_engine/arbiter.py` :1516 起的提案消费写点 + `_materialize_proposal`
物化 + `PROPOSAL_MAX_PER_RUN`/`PROPOSAL_WEEKLY_QUOTA` 节流常量 + `agents/arbiter.md`
立项节流三限契约段）在 2026-11-03 两例连续评审否决冻结后判定为车道职责越界：
框架缺口的修复成文需要设计与产品面裁量，调查报告粒度不足，立项产出必然是
占位草案。用户定调：arbiter 只修 SPEC 问题；框架缺口记 todo.md，自进化统一立项。
本 SPEC 拆通道、接路由。

## Goals / Non-Goals

**Goals**：

1. arbiter 不再产 drafted SPEC（写点/物化/常量/prompt 契约四点同步退役）
2. 框架缺口发现经报告 gaps 数组 → todo.md 落条目（可立项粒度 + 来源标记）
3. 台账 kind 演进 gap-noted，切换窗容错

**Non-Goals**：

- 不动 spec-review 晋升 lint 的缺 tasks.md 放行语义（fast-track 依赖，本 SPEC
  拆通道后该放行不再被 arbiter 草案利用）
- 不动 `add_spec` 存在性查重与白名单处置动作面
- 不改自进化车道 todo 消费机制（既有机制直接接手）
- 不清洗台账既有 `spec-proposed` 条目（append-only）

## Decisions

**D1 报告 schema 同 commit 切换**：`agents/arbiter.md` 的 proposals 数组与
`arbiter.py` 消费端同 commit 改为 `gaps`，不做双字段过渡——arbiter run 无记忆、
由 daemon 派发，重启后新 prompt 即生效；仅存切换窗在飞 run 产旧字段的窗口，
消费端按「未知字段容错」处理：检测到 `proposals` 键即记 WARNING 台账
（gap-noted 附退役说明）后丢弃，不抛异常不落池。

**D2 todo 写入复用既有锁与结构契约**：`core/fs_utils` 的 todo.md 锁（原为
evolution 私有、已升公共归属）+ `core/todo_format.py` 结构契约单源；条目字段
沿用既有五标签（影响/证据/调查评估/建议 + 自进化评估占位），来源标记以
`[arbiter:<签名前8>]` 前缀落在条目标题行，正文带触发 run_id。自省侧
`_append_todo` 的锁原语直接复用，不改 todo_format（现有标签够用）。

**D3 轻量同主题去重**：记 todo 前对既有未消费条目做标题主题匹配（关键词包含
判定，同 D7 时代的节流语义弱化版），命中则跳过并落台账 `gap-noted`（附已存在
条目行号）；不追求精确语义去重——todo 是人读队列，漏记可由人工补，重复记可
由自省合并，宁轻勿重。

**D4 立项写点退役形态**：整段移除（不留 config 开关——用户红线是边界而非
可调行为）；`_materialize_proposal` 与两节流常量一并删除；相关 import 清理。
消费方法退役后，调查报告处理流程中提案消费步骤直接跳过（gaps 为空时零动作）。

**D5 prompt 契约改写范围**：`agents/arbiter.md` 三处——(a) :34 红线段「修复走
裁决包建议人类或立项」→「修复走裁决包建议人类，框架缺口记 todo 由自进化立项」；
(b) :61-65 立项节流三限段整体替换为 gaps 上报纪律（gaps 数组按可立项粒度填
写：topic/证据/影响面/候选方向）；(c) :92 报告 schema 的 proposals 字段改 gaps。
prompt 契约段属 merge 冲突面（契约段=动态段惯例），实现分支合回前先 merge main。

## Risks

- **切换窗丢提案**：D1 容错只记台账不落 todo，理论上旧 run 的缺口发现仅存
  台账——可接受：该窗口极短（重启窗），且台账留痕可人工捞
- **todo 主题匹配误跳**：D3 关键词包含判定可能误判同主题——影响是少记一条，
  台账留痕可人工补记
- **prompt merge 冲突**：arbiter.md 契约段为动态段惯例落点，合回冲突时按
  「先 merge main 再改」纪律处理（实现任务书内注明）

## Migration

无数据迁移：ledger append-only 不清洗；todo.md 无存量 arbiter 条目；STATE 无
arbiter 来源在池条目（两条占位草案已软删除归档）。daemon 合并后需重启生效
（restart_request 交付项）。
