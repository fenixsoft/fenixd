## ADDED Requirements

### Requirement: 知识真相源配置项

配置 SHALL 新增 `knowledge` 段：`knowledge.enabled`（bool，默认 true，false 时归档不派发蒸馏且项目知识页签显示「知识真相源已禁用」占位）。配置模板 `config.template.yaml` SHALL 同步登记，且 Dashboard 设置页 SHALL 提供对应编辑控件（新增配置项必须带 Dashboard 界面）。配置热更新语义沿用既有机制。

#### Scenario: 禁用后全链静默

- **WHEN** 用户在设置页将 `knowledge.enabled` 置为 false 并归档一个 SPEC
- **THEN** 归档正常完成，但不派发蒸馏 run；项目知识页签显示禁用占位而非报错

#### Scenario: 设置页可见可改

- **WHEN** 用户打开 Dashboard 设置页
- **THEN** 能看到 `knowledge.enabled` 控件（含说明文案），修改后保存生效，无需重启 daemon
