# specs/whitelist-tracked-patrol/spec.md

## ADDED Requirements

### Requirement: 白名单脱落检测流

主树盘点 SHALL 在既有未跟踪散件流之外新增独立检测：对 git check-ignore 判定中被 `!` 放行（negation）规则命中的路径，若该路径不在 git 索引中，则产生 whitelist_untracked 信号。

#### Scenario: 放行文件被移出索引即报

- **WHEN** 某被 !.fenix/verify.yaml 放行的文件被 git rm --cached 移出索引但盘上仍存在
- **THEN** 下一轮盘点产生 whitelist_untracked 信号且该文件不计入散件计数

#### Scenario: 正常白名单文件不误报

- **WHEN** 白名单文件处于 tracked 态
- **THEN** 不产生 whitelist_untracked 信号
- **AND** 其余未跟踪散件的既有告警行为不变

### Requirement: 信号接入唤起

whitelist_untracked 信号 SHALL 登记为可唤起类型（severity major，对齐 maintree_untracked_stray_escalated 先例），文案 SHALL 说明 negation 放行即声明入库意图、放行+未跟踪约等于脱落事故。

#### Scenario: 信号唤起与裁决

- **WHEN** whitelist_untracked 信号产生
- **THEN** 其进入可唤起信号集并附处置建议（恢复入库或移除放行规则二选一）

### Requirement: 同指纹去重

同一路径集合的 whitelist_untracked 信号 SHALL 按指纹去重，不因周期盘点重复唤起。

#### Scenario: 重复盘点不重复告警

- **WHEN** 连续多轮盘点中放行-未跟踪集合未变化
- **THEN** 仅首轮产生新信号，后续轮次复用既有信号留痕
