# 知识真相源配置

<!-- knowledge: capability=knowledge-config rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas -->

真相源机制的配置开关：`knowledge` 配置段，控制归档是否派发蒸馏。

## 规则

- `knowledge.enabled`（bool，缺省 true）为总开关：false 时归档照常完成但不派发蒸馏 run，项目知识页签显示「知识真相源已禁用」占位而非报错。
- 非法值护栏（软校验）：`enabled` 键存在且类型非法时不进硬失败路径——只记 ERROR 告警，生效值由读取器按缺省回退 true；坏配置在场时逐周期重复打印同一告警（同一坏点只首告一次），不中断 30s 配置热更新。
- 登记面：`config.template.yaml` 登记带注释模板行；设置页「归档」页签的知识设置卡片承载开关控件与说明文案，保存走既有配置 POST 链路，改后约 30s 热更新生效、无需重启 daemon。
- `knowledge` 段同时承载维护车道开关（`audit_enabled` 等键，规则见 knowledge-audit 页）；`knowledge-distiller` 在 KNOWN_AGENT_TYPES 登记为已知 agent 角色——`agents.models.knowledge-distiller` 可配模型与超时，不配置时走默认网关。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：knowledge.enabled 缺省与禁用语义、非法值回退、模板与设置页登记、knowledge-distiller 角色立项即登记
