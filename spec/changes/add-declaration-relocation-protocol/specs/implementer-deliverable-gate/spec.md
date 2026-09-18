# implementer-deliverable-gate — 增量规格（声明解析源与收缩防护）

## ADDED Requirements

### Requirement: 声明收缩防护

收工守卫 MUST 以派发时落盘的**可信基线快照**（见 `deliverable-declaration-resolution`）
为参照做收缩判定：基线中的路径若在生效声明中被**无声剔除**（生效声明不再含该路径，
且该路径在实现分支 HEAD 也不满足其原有 kind 要求），MUST 判为收缩违规（`removed`）。
收缩违规 MUST NOT 因「声明不再声明它」而放行——它等价于把交付物从声明里删掉绕门。

合法豁免（不判收缩违规）仅限两类：（1）该路径有**重定位凭据**在册（旧路径 → 替代
路径已机械改写并审计，见 `declaration-relocation-protocol`）；（2）生效声明对该路径
的 kind 被合法裁决软化（`reference`，且审计留痕）。

基线快照不可用（未落盘 / 读取失败）时，收缩防护 MUST 降级为保守策略——不因缺基线
而误伤正常轮次，但 MUST 审计留痕说明本轮未做收缩判定。

#### Scenario: 删声明行绕门被拦

- **GIVEN** 基线快照含 `core/x.py`（kind: modify），实现分支 HEAD 上该路径不存在，
  且生效声明已删除 `core/x.py` 条目（无重定位凭据、无软化审计）
- **WHEN** 收工守卫对账
- **THEN** 该条判违规 `{"path": "core/x.py", "kind": "modify", "violation": "removed"}`
- **AND** MUST NOT 放行 merge

#### Scenario: 重定位豁免不判收缩

- **GIVEN** 基线含 `core/old.py`，生效声明已将其重定位为 `core/new.py`（凭据在册、
  审计留痕）
- **WHEN** 收工守卫对账
- **THEN** MUST NOT 对 `core/old.py` 判收缩违规（重定位豁免）

#### Scenario: 无基线时保守降级

- **WHEN** 本轮基线快照缺失或读取失败
- **THEN** 收缩防护不产生违规条目
- **AND** 审计留痕记录「本轮未做收缩判定」

### Requirement: 陈日声明前置分类

收工守卫在产生缺件清单后、进入 LLM 终审之前，MUST 先对缺件条目做**陈日声明**
确定性分类（见 `declaration-relocation-protocol` 的确定性信号）：命中陈日信号的
条目 MUST 走重定位通道，MUST NOT 直接落入「缺件 → 打回重派」。

该分类为纯机械判定（基线树存在性），MUST NOT 触发 LLM。分类后剩余的非陈日缺件
方进入既有终审/裁决流程。

#### Scenario: 陈日声明不走重派

- **GIVEN** 缺件 `core/pm_engine/dispatch.py`（kind: modify）在基线树已被上游删除
- **WHEN** 守卫产生缺件清单
- **THEN** 该条被前置分类为陈日声明，走重定位通道
- **AND** MUST NOT 直接按缺件打回重派

#### Scenario: 非陈日缺件正常进入终审

- **GIVEN** 缺件 `core/new_module.py`（kind: new，应本轮新建但未落地）
- **WHEN** 守卫产生缺件清单
- **THEN** 该条不命中陈日信号，进入既有 LLM 终审/裁决流程

## MODIFIED Requirements

### Requirement: 收工时存在性校验

实现 run 声明成功后、merge 之前，系统 MUST 对**生效声明**（经统一解析入口取得，
分支/worktree 版本优先、主树回退，见 `deliverable-declaration-resolution`）的
`deliverables` 组中每个条目，在**实现分支 HEAD** 上按 kind 校验达成条件：
`new`/`modify` 要求该路径 blob 存在，`delete` 要求该路径 blob 不存在。任一未达成
→ 本次 run MUST NOT 执行 merge、MUST NOT 推进状态，按既有失败路径处置。

校验的**声明来源** MUST 为统一解析入口的分层结果（分支优先），MUST NOT 硬编码读
主树 `project_root/spec/changes/<spec>/tasks.md`——后者是实现方与验收方错层的根因
（上游重构致规划期声明路径失效时，主树声明陈旧且永不满足，重派复用同分支原地打转）。

校验结果 MUST 以结构化条目列表返回（每项含 `path` / `kind` / `violation`，
`violation ∈ {missing, undeleted, removed}`），而非裸路径列表——下游（dispute 匹配、
LLM 终审、重派话术）据此按 kind 分化表述与可用归宿。`removed` 为收缩防护产出
（见「声明收缩防护」）。

#### Scenario: 缺件阻断 merge

- **GIVEN** 生效声明含 `core/x.py`（kind: new）且实现分支 HEAD 中该 blob 不存在
- **WHEN** 实现 agent 报成功
- **THEN** 不执行 merge、不推进状态
- **AND** 守卫返回项含 `{"path": "core/x.py", "kind": "new", "violation": "missing"}`
- **AND** error 记录违规清单（含「交付物守卫」字样），按既有重试路径重派实现

#### Scenario: 声明取自分支而非主树

- **GIVEN** 主树 tasks.md 声明 `core/pm_engine/dispatch.py`（已上游删除），实现分支
  HEAD 的 tasks.md 已对齐为 `core/pm_engine/dispatch/adjudication.py`（存在）
- **WHEN** 实现 agent 报成功
- **THEN** 守卫以分支声明为基准，判定全部达成
- **AND** MUST NOT 因主树陈旧声明判缺件、MUST NOT 重派

#### Scenario: 全部达成时放行

- **GIVEN** 生效声明全部条目的达成条件在实现分支 HEAD 成立（new/modify 存在、
  delete 不存在）
- **WHEN** 实现 agent 报成功
- **THEN** 走既有 merge 与推进路径，守卫不产生额外状态变更
