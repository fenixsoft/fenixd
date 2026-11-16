# judge-env-attribution Specification

## ADDED Requirements

### Requirement: env 归因必须引用可复核环境量测

judge 对场景失败作出 env 归因时，evidence MUST 包含至少一项可复核的环境量测（负载/CPU/温度/驱动版本等具体数值及其来源），且 MUST 包含至少一个验证窗口外的对照样本（同宿主历史轮次或窗口外重跑）；两者缺一时不得给出 env 归因的 accept 结论。

#### Scenario: 有量测有对照的 env 归因被接受

- **WHEN** judge 的 env 归因 evidence 同时含环境量测数值与窗口外对照样本
- **THEN** 归因按现有流程 accept 并入档 judge_attribution.json，新字段（量测引用、对照样本引用）随条目落盘

#### Scenario: 无量测或无对照的 env 归因被降级

- **WHEN** judge 给出 env 归因但 evidence 缺环境量测数值或缺窗口外对照样本
- **THEN** 归因不落 accept，产出 status=inconclusive 的归因条目，并在 evidence 中注明缺失项

### Requirement: inconclusive 归因自动进 recheck 且不进豁免握手

被降级为 inconclusive 的 env 归因 MUST 走既有 inconclusive_loop/recheck 通道等待补充证据，MUST NOT 直接驱动豁免握手（env 三选一）或以 env-accept 语义进入收尾。

#### Scenario: inconclusive 归因不触发豁免握手

- **WHEN** 某场景的失败归因被降级为 inconclusive
- **THEN** 该场景进入 recheck 通道（复用 core/alert_lifecycle.py 与 core/event_bus.py 的既有 inconclusive_loop 路径），豁免握手不被触发

#### Scenario: 补充对照后重新归因

- **WHEN** recheck 轮次中 judge 拿到窗口外对照样本后重新给出 env 归因
- **THEN** 归因按证据门重新评估，满足条件才 accept

### Requirement: 归因产物 schema 可承载证据引用

judge_attribution.json 的条目 schema MUST 支持记录量测引用与对照样本引用字段；schema 变更 MUST 向后兼容（旧文件缺字段可读取）。

#### Scenario: accept 条目带证据字段落盘

- **WHEN** 一个 env 归因被接受
- **THEN** 落盘条目包含量测引用与对照样本引用字段，消费方可据此复核

#### Scenario: 旧格式文件兼容读取

- **WHEN** 读取不含新增字段的既有 judge_attribution.json
- **THEN** 解析不失败，缺失字段按空处理