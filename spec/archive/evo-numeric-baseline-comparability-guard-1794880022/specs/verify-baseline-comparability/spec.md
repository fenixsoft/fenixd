# verify-baseline-comparability Specification

## ADDED Requirements

### Requirement: 跨轮稳定性快照携带 progress 指纹

verdict_stability 快照 MUST 增记当轮 progress 摘要指纹（至少含组合条数与 progress 中可用的采集/编码几何、管道版本元数据摘要）；相邻两轮指纹不一致时，快照与稳定性报告 MUST 显式标注「基线不可比」。指纹字段 MUST 向后兼容（旧快照缺字段可读取）。

#### Scenario: 几何漂移在稳定性快照中显形

- **WHEN** 相邻两轮的 progress 几何指纹不一致（如采集分辨率变更）
- **THEN** verdict_stability 快照标注「基线不可比」，稳定性报告呈现漂移明细，验证链消费者可直接看到跨轮数值不可直接对比

#### Scenario: 旧快照兼容读取

- **WHEN** 读取不含指纹字段的既有 verdict_stability 数据
- **THEN** 解析不失败，缺失字段按未知处理且不阻断稳定性比较

### Requirement: 裁决证据包声明基线可比性

裁决/仲裁证据包（adjudication narrative）MUST 在包含跨轮数值比较时声明所用基线的可比性（几何与管道元数据是否一致）；不可比时 MUST 标注「不可比」，MUST NOT 直接据此得出回归/豁免定性。

#### Scenario: 证据包含可比性声明

- **WHEN** 证据包引用跨轮数值基线比较
- **THEN** 包内呈现基线元数据（或「元数据缺失」）与可比性结论，比较数值附带可比性标注

#### Scenario: 不可比基线不支撑定性

- **WHEN** 跨轮基线不可比（几何漂移或元数据缺失）
- **THEN** 证据包对该比较标注「不可比」，不将其作为产品回归或 env 豁免的定性依据

### Requirement: 仲裁对跨轮数值比较先核可比性

arbiter 对跨轮数值基线做比较时 MUST 先核对采集/编码几何与管道版本的可比性，不可比或元数据缺失时 MUST 显式标注不可比并降级结论确定性，MUST NOT 把不可比差异直接定性为产品回归或环境豁免。

#### Scenario: 几何不一致的跨轮比较被拦下

- **WHEN** arbiter 比较的新旧两轮 progress 几何信息不一致或缺失
- **THEN** 仲裁结论将数值差异标注为不可比、结论降级为待查，不产生回归/豁免定性

#### Scenario: 几何一致的比较正常进行

- **WHEN** 新旧两轮几何与管道元数据一致
- **THEN** 比较按现有流程进行，结论不降级