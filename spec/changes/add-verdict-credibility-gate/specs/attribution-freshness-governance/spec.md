# spec: attribution-freshness-governance（归因新鲜度治理）

## ADDED Requirements

### Requirement: 跨轮缓存归因必须打新鲜度标

verdict_cache（跨轮指纹缓存）命中的场景归因在写入 report / 打回上下文时，必须携带「跨轮缓存复用」标记，禁止以本轮新证据的口径原样呈现。

#### Scenario: 指纹命中归因带缓存标

- **WHEN** 本轮场景指纹与 verdict_cache 中历史条目一致并复用其归因
- **THEN** 该归因输出附 `cached_from_previous_round: true` 与来源轮次信息
- **AND** 打回上下文的消费者（implementer prompt、report 渲染）可见该标记

#### Scenario: 缓存归因不得作为本轮唯一打回依据

- **WHEN** 本轮打回依据全部来自缓存归因（无本轮新增 evidence-backed 证据）
- **THEN** 与 verdict-attribution-evidence-gate 的推测级同规则处理（抑制打回，转重验或人工复核）

### Requirement: 禁止批量硬编码归因落盘

报告合成/丰富路径（含 judge 自建脚本）不得将同一硬编码归因文案批量套用到多个场景。

#### Scenario: 批量同文案归因被拒绝

- **WHEN** 单轮落盘的多个场景归因文本完全一致（归一化空白后逐字相同）且场景数 ≥ 3
- **THEN** 合成器拒绝落盘并记 error 日志（列出涉及场景），要求逐场景归因
- **AND** 校验内置在框架的 report 合成/丰富入口（不依赖人工审查发现 judge 自建脚本）

### Requirement: 视觉基线防污染

视觉基线建立（首跑固化）时必须做健全性判定，环境性伪画面不得固化为基线。

#### Scenario: 白屏不得固化为基线

- **WHEN** 首跑建立视觉基线时截图命中 blank_screenshot / low_contrast 标签
- **THEN** 拒绝固化该基线，场景视觉断言按环境存疑处理（记 warning，不产生像素比对结论）
- **AND** 后续轮次该场景重新尝试建立基线（干净截图成功后正常固化）

#### Scenario: 基线建立失败可观测

- **WHEN** 基线因防污染被拒绝固化
- **THEN** report 中该场景记录「baseline_rejected + 原因标签」，供人工与后续轮次追溯
