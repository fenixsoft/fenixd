# adjudication-alert-narrative Spec

## REMOVED Requirements

### Requirement: 转人工裁决告警附带三段式叙事
**Reason**: 用户决策不再为告警派 Agent 生成调查叙事；告警以机械文案自足可裁决，LLM 叙事属可退役的成本与延迟负担。
**Migration**: 写告警时不再发起叙事生成、不再写 narrative 字段；历史侧车报告与 arbiter 车道写入 narrative 槽位的调查报告经读侧合并照常渲染（见 MODIFIED「前端告警区渲染叙事」）。

### Requirement: 叙事覆盖全部转人工裁决告警
**Reason**: 生成链整体退役，不存在需要覆盖的发射点集合。
**Migration**: 汇聚写入口（`_send_human_escalation_alert`）与旁路点（mergeback、token_budget）拆除叙事 attach 调用；告警结构化字段（description/evidence/recommended_action/choices/trigger）语义不变。

### Requirement: 叙事失败兜底 fail-open
**Reason**: 无生成即无失败面；超时与 fail-open 语义随生成链退役。
**Migration**: 无迁移；历史失败说明侧车按普通历史 narrative 内容渲染。

### Requirement: 叙事开关与配置
**Reason**: 生成链退役后三个配置项（`admin.narrative_enabled`/`admin.narrative_timeout_seconds`/`admin.narrative_model`）失去被控对象，配置面一并收缩。
**Migration**: config.template.yaml admin 段三键注释与设置页 SystemPanel 对应控件移除；存量用户 config 中的 narrative_* 键被 loader 容忍（未知键忽略），不报错。

## MODIFIED Requirements

### Requirement: 前端告警区渲染叙事

Dashboard 告警区 SHALL 在证据（evidence）之前渲染告警记录已合并的 narrative 槽位内容（Markdown 渲染，默认展开，保留「AI 生成」标注）；内容来源仅为历史侧车报告（`.fenix/admin_alerts_narrative/<alert_id>.json`，读侧合并与告警清理级联删除保持不变）与 arbiter 车道写入的调查报告。系统 MUST NOT 再发起任何叙事生成调用：新告警 MUST NOT 出现 narrative 字段，MUST NOT 渲染「调查生成中」占位或任何 pending 态。记录无 narrative 槽位内容时保持既有渲染不变。choices 下拉与执行按钮的交互 MUST 与现状一致（叙事仅为可读性增强，不承载任何机器语义）。

#### Scenario: 历史侧车报告照常渲染
- **WHEN** 用户查看一条退役前生成过叙事侧车的告警
- **THEN** 证据前照常显示该报告内容（带 AI 生成标注），内容与退役前一致

#### Scenario: arbiter 调查报告渲染
- **WHEN** 一条告警的 narrative 槽位被 arbiter 车道写入调查报告
- **THEN** 告警区在证据前渲染该报告，交互与现状一致

#### Scenario: 新告警无叙事无占位
- **WHEN** 退役后一条新的转人工裁决告警写入且用户查看
- **THEN** 告警以机械文案完整渲染，无 narrative 字段、无「调查生成中」占位、无 pending 态

#### Scenario: 长叙事不破坏布局
- **WHEN** narrative 文本超过 2000 字符
- **THEN** 告警卡片以既有序列化容器规则折叠/滚动展示，不横向溢出、不遮挡 choices 操作区
