# error-attribution-denoise — 错误归因降噪

## ADDED Requirements

### Requirement: error 消息过滤 CLI stderr 诊断噪音行

runner 在进程非零退出拼装 error 消息（现取 stderr 末 5 行拼接）时，MUST 先过滤匹配 `^\[claude-code:` 的 stderr 诊断噪音行（v2.1.233+ 每请求写入、与死因无关）；过滤后无剩余内容时回退 `Exit code: {returncode}` 形态。run 产物 jsonl 中的 stderr 原始事件行保持原样不过滤（取证现场完整）。瞬断判定与 dispatch 分类不得依赖降噪后的 error 字符串反推，必须使用原始 stderr 信号或结构化标记。

#### Scenario: 死因不再被诊断行误标

- **GIVEN** claude 进程死亡，stderr 末 5 行均为 `[claude-code:...]` 诊断行
- **WHEN** runner 拼装 error 终态消息
- **THEN** error 文本不含 `[claude-code:` 前缀内容；产物 jsonl 中 stderr 原始事件行完整保留

#### Scenario: 全噪音回退退出码形态

- **GIVEN** 进程非零退出且 stderr 全部为诊断噪音行，无其他有效内容
- **WHEN** 拼装 error 终态消息
- **THEN** error 文本为 `Exit code: {returncode}`（returncode 为实际退出码）
