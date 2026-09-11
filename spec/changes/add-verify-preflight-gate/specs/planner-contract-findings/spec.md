# spec-planner-contract-findings

## ADDED Requirements

### Requirement: planner 出题期契约只读一致性检查

planner-plan 出题阶段（场景文件落盘前后均可，fail-open）框架 SHALL 对验证契约执行只读一致性检查（零 token、纯机械），初始检查项：

- serve.kind=command 且 cmd 含脚本入口路径 → 入口文件存在性（与预检同源解析器，但此处在出题期提前暴露）；
- package.json 的 `start` script 存在时，其入口路径与 serve.cmd 入口的一致性（不一致仅提示不拦截——两者差异可能是合法设计）；
- 场景集 URL 端口与契约 serve 端口/`{port}` 占位符的形态提示。

检查结果结构化落盘 `.fenix/verify-progress/<spec>/contract_findings.json`（字段：rule_id / severity / message / evidence）。检查项任何异常（文件缺失、解析失败）记 WARNING 跳过，不阻断出题。

#### Scenario: 入口路径偏差在出题期落盘

- **WHEN** planner 出题时契约 serve.cmd 指向 `dist/server.js` 而 package.json start 为 `dist/server/index.js`
- **THEN** contract_findings.json 落盘 entry「serve_entry_mismatch」，evidence 含两个路径原文

#### Scenario: 契约正确时 findings 为空

- **WHEN** 契约 serve.cmd 入口存在且与 start script 一致
- **THEN** contract_findings.json 为空数组或不存在，零注入

### Requirement: 契约 findings 注入 admin 处置 prompt

Administrator 处置派发时，框架 SHALL 在 prompt 中注入契约 findings 段（复用 `_scenario_static_findings_section` 同款机制）：逐条 rule_id + message + evidence，并声明「本情报为机械检出，处置前请以源码/执行证据核实」。findings 缺失/为空/损坏 → 返回空串（零注入，prompt 与现状逐字节一致）。

#### Scenario: admin 处置收到契约偏差情报

- **WHEN** add-web-ui 型事故触发 verify_env_blocked 处置，且 contract_findings.json 含 serve_entry_mismatch
- **THEN** admin prompt 含该情报段，处置可直接定位入口路径错误（而非全链重查）

#### Scenario: 无 findings 的处置 prompt 零变化

- **WHEN** 处置派发时 contract_findings.json 不存在
- **THEN** admin prompt 与现状逐字节一致
