# spec-dashboard-chain-editor

## ADDED Requirements

### Requirement: 多 provider 链的可视化编辑
Dashboard 设置界面的 agent 分配区 SHALL 支持对每个角色渲染可排序的候选链编辑器：每行为 provider 下拉（选项来自 llm.providers）+ 可选 model 文本框（占位提示"留空用角色级缺省"）；提供添加行、删除行、上移/下移操作；加载时 SHALL 识别 str、str 列表、对象列表三种既有形态并规范化回显。

#### Scenario: 链的加载与回显
- **WHEN** 配置 `provider: [{provider: a, model: m1}, b]`、角色级 `model: m0`
- **THEN** 编辑器显示两行：第 1 行 provider=a model=m1，第 2 行 provider=b model 占位显示 m0

#### Scenario: 列表操作
- **WHEN** 用户添加一行、调整顺序并删除一行后保存
- **THEN** config.yaml 中该角色的 provider 按最终行序序列化

### Requirement: 保存序列化与防覆写
保存 SHALL 将编辑器状态序列化：单行且该行无元素级 model → 字符串形态；否则对象/字符串数组。后端 config_patch 应用前 MUST 以 _validate_agent_models 校验，失败返回 400 与原因，配置不落盘；patch 组装 MUST 以表单整体状态替换该角色条目，禁止部分字段混拼。

#### Scenario: 单行退化为字符串
- **WHEN** 编辑器仅一行 provider=a 且 model 留空、角色级 model=m0
- **THEN** 保存后 config 中 provider 为字符串 `"a"`

#### Scenario: 非法链被拒绝不落盘
- **WHEN** 用户构造全部元素均无模型的链且无角色级缺省……该情形按 chain-model-mapping 属合法（校验通过）；本场景改为：provider 名不存在于 llm.providers
- **THEN** 保存返回 400 与「引用了不存在的 provider」信息，config.yaml 未被修改

#### Scenario: 已有链不被单值覆写
- **WHEN** YAML 中某角色为对象数组链，用户在界面打开设置并直接保存（未改该角色）
- **THEN** 该角色链保持数组形态与元素级 model 不变
