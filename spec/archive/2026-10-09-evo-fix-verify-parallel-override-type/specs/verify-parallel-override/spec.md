# verify-parallel-override 规格

## ADDED Requirements

### Requirement: 降档覆盖字段类型契约
_verify_parallel_override SHALL 只接受 int（并行度）或 null（复位）；人工处置写点 SHALL 写 null 复位而非布尔值。

#### Scenario: 复位写 null
- **WHEN** reset_verification / continue_auto_fix 等人工处置复位该字段
- **THEN** 写 null，STATE.md 往返读回 null，验证启动沿用配置并行度且无解析告警

#### Scenario: 非法形状拦截
- **WHEN** 写入侧收到布尔或字符串形态的该字段值
- **THEN** 在解析/写入层拒绝并告警（或归 null），不静默序列化进 STATE.md

### Requirement: 解析失败可诊断
读端对非法值 SHALL 降档沿用配置并行度并留痕值形状。

#### Scenario: 非法值告警
- **WHEN** 读端遇到不可解析的覆盖值
- **THEN** 告警含 repr 形态与字段来源，不把布尔语义映射为特定并行度