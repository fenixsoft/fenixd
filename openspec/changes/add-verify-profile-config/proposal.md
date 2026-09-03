## Why

planner/verifier/planner-judge 的 prompt 存在三类硬编码腐烂：已死知识（AMIS 选择器大全随 v2 删除仍残留 ~19 行 + 2 处示例）、被管产品领域规范硬编码进通用框架（云端 COS e2e、壳路由 href、verifier Step 3 强制回归一个产品才有的面板清单 Stock/Notes/Calculator/Email——对其他项目是强制测试不存在的功能）、且"事故→追加段落"只增不减，今天 planner 78 轮全量 prefill 直接受其放大。框架选型与领域断言是项目级事实，必须由用户可设置，而非写死在程序里。

## What Changes

- `.fenix/verify.yaml` 新增 `profile:` 键：项目验证档案条目列表（`id` / `agents` 适用 agent 列表 / `text` Markdown 正文），用户可设置
- prompt_builder 构建对应 agent prompt 时读取 verify.yaml 的 profile 条目，按 `agents` 字段过滤后注入为「项目验证档案（用户配置）」段；无条目时 prompt 与现状逐字节一致（零注入）
- 清理死知识（不入档案）：planner 的 AMIS 选择器大全、planner-judge 的 `.dark-Card` 示例、interaction_contract_section 的 `dark-Card--link` 示例
- verifier Step 3 的被管产品面板清单（Quick Links/Stock/Notes/Calculator/Email）替换为通用表述（点击遍历被测应用每个主要界面，交互必须有可见结果）
- 迁移项目特定知识入 fenixd 自身 `.fenix/verify.yaml` 档案（知识保留、出框架代码）：云端 COS e2e 规范、壳路由 href 规范、seed 键合法格式示例
- Dashboard 设置页「验证」页签新增「项目验证档案」编辑区（条目增删改、保存落盘 verify.yaml）
- 范围外（登记不修）：administrator prompt 的 Dashboard 运维手册（fenixd 自身基础设施事实，非被测项目规范）；fast-track agent prompt 是否注入档案——一并注入（它含验证阶段），列入任务

## Capabilities

### New Capabilities
- `verify-profile-config`: 项目验证档案——verify.yaml `profile` 键 schema、prompt 注入规则（agents 过滤、无条目零注入）、Dashboard 验证页签编辑能力、死知识清理与迁移清单

### Modified Capabilities
（无 spec 级行为变更的既有能力）
