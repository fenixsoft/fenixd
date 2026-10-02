# planner 出题期契约发现（planner-contract-findings）

<!-- knowledge: capability=planner-contract-findings rev=1
     sources=spec/archive/2026-09-18-add-verify-preflight-gate -->

planner-plan 出题阶段的验证契约只读一致性检查通道：契约偏差结构化落盘并送达 admin 处置，侦测必送达。

## 规则

- planner-plan 出题阶段（场景文件落盘前后均可），框架对验证契约执行只读一致性检查：零 token、纯机械、fail-open——检查项任何异常（文件缺失、解析失败）记 WARNING 跳过，不阻断出题。
- 初始检查项：
  - serve.kind=command 且 cmd 含脚本入口路径 → 入口文件存在性（与预检同源解析器，在出题期提前暴露）；
  - package.json `start` script 存在时，其入口路径与 serve.cmd 入口的一致性（不一致仅提示不拦截——两者差异可能是合法设计）；
  - 场景集 URL 端口与契约 serve 端口/`{port}` 占位符的形态提示。
- 检查结果结构化落盘 `.fenix/verify-progress/<spec>/contract_findings.json`，字段：`rule_id` / `severity` / `message` / `evidence`。
- 契约正确时 findings 为空数组或文件不存在，零注入。
- Administrator 处置派发时，prompt 注入契约 findings 段（复用 `_scenario_static_findings_section` 同款机制）：逐条 `rule_id` + `message` + `evidence`，并声明「本情报为机械检出，处置前请以源码/执行证据核实」。
- findings 缺失/为空/损坏 → 返回空串零注入，admin prompt 与无 findings 时逐字节一致。

## 溯源

- 2026-09-18 2026-09-18-add-verify-preflight-gate（spec/archive/2026-09-18-add-verify-preflight-gate） — 新增出题期契约只读检查（入口存在性、start 入口一致性、端口形态提示）、contract_findings.json 落盘与 admin 处置 prompt 注入通道。
