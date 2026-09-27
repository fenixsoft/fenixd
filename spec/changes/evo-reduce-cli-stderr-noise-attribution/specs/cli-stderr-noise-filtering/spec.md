# cli-stderr-noise-filtering

## ADDED Requirements

### Requirement: CLI stderr 诊断噪声统一判别
框架 SHALL 把 claude CLI 的启动期诊断噪声（[claude-code:*] 族，含 unrecognized_model）定义为可复用的噪声 pattern 常量，供各消费端统一判别；常量 SHALL 派生自既有 UNRECOGNIZED_MODEL_TEXT_PATTERNS，且 SHALL NOT 改变 provider_circuit 的瞬态分类判据与瞬断判定。

#### Acceptance Scenario 1: pattern 统一且瞬态判据不变
- WHEN 任一消费端判别某 stderr 行是否为诊断噪声
- THEN 使用同一 pattern 常量判定
- AND provider_circuit 的分类行为（unrecognized_model 不算瞬态）保持不变

### Requirement: 深扫 first_stderr 降噪
自省中途信号深扫收集 stderr 时，first_stderr 摘要 SHALL 取首条非噪声行；stderr 计数 SHALL 保留全量（含噪声行）；stderr 全为噪声行时 first_stderr SHALL 置空而非回填噪声。

#### Acceptance Scenario 2: 噪声不占位
- WHEN run stderr 首条为 unrecognized_model 噪声、后续存在真实诊断行
- THEN first_stderr 取首条真实诊断行，stderr_count 仍统计全部行

#### Acceptance Scenario 3: 全噪声置空
- WHEN run 的 stderr 全部为噪声行
- THEN first_stderr 为空，不回填噪声行

### Requirement: 失败归因文本降噪
失败归因文本（stderr 尾部截取）SHALL 先过滤噪声行再截取；过滤后为空时 SHALL 回退 stdout 尾部，保证真实故障证据（如 429 限流文本）可进入归因。

#### Acceptance Scenario 4: 真实死因不被淹没
- WHEN run 失败且 stderr 仅含噪声行、stdout 含「API Error: Request rejected (429)」类真实错误
- THEN 归因文本不含噪声行且包含 stdout 中的真实错误片段