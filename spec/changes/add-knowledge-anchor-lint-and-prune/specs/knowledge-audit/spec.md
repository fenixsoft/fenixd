## ADDED Requirements

### Requirement: 病灶⑥锚点悬空检测

知识体检病灶族新增第六类「锚点悬空」：`core/knowledge.py` 新增
`check_anchor_references(project_root) -> list`，只扫描各能力页 `## 代码锚点`
段内的路径 token，逐一生成仓库相对路径并校验盘上存在性（`spec/archive/`、
`spec/knowledge/_inbox/`、`node_modules/` 下路径跳过）；悬空项进体检报告
「待人工/定向转写」档计数与明细。该检查 MUST NOT 并入
`validate_knowledge` 硬门（防一处陈旧锚点阻塞全树折叠校验），MUST NOT 机械
自删悬空锚点行（修复需语义判断，删除丢信息）。

#### Scenario: 悬空锚点进报告

- **WHEN** 某能力页代码锚点段引用 `core/foo.py` 且该文件不存在，到达下一轮体检
- **THEN** 体检报告病灶⑥计数 +1 并列明页与路径， truth source 其余校验不受影响

#### Scenario: 锚点段外路径不扫

- **WHEN** 能力页规则段/溯源段内提及路径 `core/foo.py` 且文件不存在
- **THEN** 不计病灶⑥（锚点纪律只约束锚点段；溯源段悬空由既有溯源检查管辖）

#### Scenario: 不阻塞折叠硬门

- **WHEN** 真相源存在一处悬空锚点，蒸馏轮折叠另一能力页并跑实时校验
- **THEN** 校验不因病灶⑥失败，折叠正常落盘

### Requirement: ADR retired 校验放行

`_ADR_STATUS_RE` 扩展接受 `retired`；retired 条目 MUST 含 `Retired:` 注记行
（缺失报违规），三段正文逐字不可改写（同 superseded 纪律）；
`accepted | superseded` 既有校验行为零变化；adr/index.md 状态与条目头一致性
检查覆盖 retired 值。

#### Scenario: retired 全链校验

- **WHEN** 五条存量 amis 壳/商业化域 ADR 翻为 `status: retired` + `Retired:` 行，
  adr/index.md 同步
- **THEN** validate_knowledge 全树零违规；同场景缺任一 `Retired:` 行时报违规
