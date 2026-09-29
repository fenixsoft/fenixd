<!-- knowledge: capability=dashboard-chain-editor rev=1 sources=spec/archive/2026-09-03-improve-failover-model-mapping-ui -->

# 链模型映射编辑器

设置页 agent 分配区的可视化候选链编辑器：按角色渲染可排序链行，保存时序列化回 config 并经后端校验。

## 规则

- 每个角色渲染可排序候选链编辑器：每行为 provider 下拉（选项来自 `llm.providers`）+ 可选 model 文本框（占位提示「留空用角色级缺省」）；提供添加行、删除行、上移/下移操作。
- 加载时识别 `str`、`str` 列表、对象列表三种既有形态并规范化回显：字符串元素回显 provider 名、model 占位显示角色级缺省；对象元素回显自身 model。
- 保存序列化：单行且该行无元素级 model → 序列化为字符串形态；否则按最终行序序列化为对象/字符串数组；patch 以表单整体状态替换该角色条目，禁止部分字段混拼。
- 后端 config_patch 应用前以 `_validate_agent_models` 校验：失败返回 400 与原因（如引用了不存在的 provider），配置不落盘。
- 用户未改动的角色在整体保存时保持既有链形态与元素级 model 不变，不被单值覆写。

## 溯源

- [2026-09-03 improve-failover-model-mapping-ui](spec/archive/2026-09-03-improve-failover-model-mapping-ui/) — 建立链编辑器的行级交互、三形态规范化回显、单行退化字符串的序列化规则与后端校验防覆写契约
