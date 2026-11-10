# 存量幽灵条目结构性清退通道

## Why

7f7ee45e2 只修新立项物化路径，存量幽灵条目（本例 + 孪生 fix-planner-scenario-entry-schema-selfcheck）无终态通道：只能 拒绝×2→冻结→人工升级，本例烧掉 5 个评审 run（约 $3.3 台账成本，另有 1 个被重启打断）+ 一次人工升级，才得出一个证据完全确定的「应清退」结论；存量回填也只能显式跳过「留人工排查」。建议：daemon 启动/回填期对账——非终态条目若满足幽灵指纹（注册以来 spec/changes/<name> 目录从未存在且 git 全历史对该路径零提交）→ 结构性落终态（revoked）或聚合为单条批量人工裁决清单，替代逐条 freeze→escalate。

## What Changes

- 新增幽灵条目对账清退逻辑（挂 `core/pm_engine/spec_integrity.py` 既有内容完整性闸门同域）：daemon 启动回填期 + full_scan 周期扫描 STATE 非终态条目，对命中「幽灵指纹」（非终态 + `spec_has_content` 为 False + git 全历史对 `spec/changes/<name>` 零提交 + 注册超 30 分钟，三条件同时成立）的条目执行结构性清退——`remove_spec` 原子移除 + 逐条台账留痕 + 单条聚合告警（列全部清退条目与指纹证据），替代逐条 freeze→escalate。
- 不引入新状态机状态：代码库状态机无 `revoked` 枚举（core/state_machine.py `VALID_TRANSITIONS` 终态仅 `pushed`），幽灵条目从未物化立项，「移除 + 留痕」即结构性终态语义；原提案「revoked」措辞按既有机制落地为 remove_spec 清退。
- 防误杀约束：三条件缺一不清退；注册 30 分钟内的新条目豁免（防物化/注册竞态窗口）；非法路径成分 spec 名保守跳过只告警；配置开关 `gates.ghost_entry_reclaim`（默认 on）。
- 孪生条目 `fix-planner-scenario-entry-schema-selfcheck`（STATE blocked+frozen、目录不存在、git 零提交、created 2026-10-31）为首个清退对象；本条目自身已物化 proposal.md（有实质内容），不命中指纹，走正常评审晋升流。

## Capabilities

### New Capabilities

- `ghost-entry-reclaim`: daemon 启动回填期与 full_scan 周期的幽灵条目对账清退——非终态 STATE 条目在「目录无实质内容 + git 全历史零提交 + 注册超新鲜度窗」时被结构性移除并聚合留痕，无需逐条评审冻结与人工升级。

### Modified Capabilities

（无）

## Impact

- `core/pm_engine/spec_integrity.py`：新增幽灵指纹判定与清退动作（复用 `spec_has_content` 纯函数与 full_scan 未处理告警防重先例）。
- `core/pm_engine/engine.py`：启动回填期与 full_scan 周期挂点接入。
- `core/state_machine.py`：仅调用既有 `remove_spec`（:2777），不修改状态机。
- `tests/test_spec_content_integrity.py`：指纹真值表/豁免/清退/幂等/聚合告警单测扩展。
- 不触碰 spec-review、晋升 lint、派发链路；正常条目（物化过 proposal 或有 git 历史）永不命中指纹，既有流转零影响。

---

- 立项来源：Arbiter 调查（run_id=None，signature=fix-arbiter-proposal-materialize-spec-dir::spec-review-rejected，source=escalation-alert）
- 立项时间：2026-11-01T01:22:50.659570+00:00
