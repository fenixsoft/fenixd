# draft-promotion-gate Spec

## ADDED Requirements

### Requirement: 中文标题晋升硬门

SPEC 晋升（drafted → ready）lint SHALL 机械检查 `.spec.yaml` 的 `title` 字段存在性：字段缺失或去首尾空白后为空即晋升违规，违规消息 MUST 含处方——写入示例（`title: <5-25字中文标题>` 追加至 `.spec.yaml` 末行）与规范出处（add-spec-chinese-title 生成纪律），不留零解释违规。豁免口径：spec 名以 `fix-cr-` 为前缀的 SPEC（code-fix 程序化通道，add-spec-chinese-title proposal 非目标）；其余一律必填。title 值本身不做长度/形态校验（5-25 字仍是生成纪律，读侧容错契约不变）。检查复用既有 title 读取单点语义（活跃 `.spec.yaml` 直读即可——晋升时 change 目录必在活跃侧，无需归档回退）。

#### Scenario: 缺 title 晋升被打回

- **WHEN** 某 `add-*` SPEC 晋升（drafted → ready）且其 `.spec.yaml` 无 `title` 行
- **THEN** 晋升违规（drafted + error 既有形态），违规消息含写入处方与规范出处；立项方补写 title 后周期扫描重试晋升通过

#### Scenario: 空 title 同判违规

- **WHEN** 某 SPEC 的 `.spec.yaml` 有 `title:` 行但值为空白（去首尾空后为空串）
- **THEN** 与缺失同判晋升违规，消息同处方

#### Scenario: fix-cr-* 豁免

- **WHEN** 某 `fix-cr-*` 前缀 SPEC 晋升且无 `title` 行
- **THEN** 不违规，晋升流程与改动前一致

#### Scenario: 有 title 晋升零变化

- **WHEN** 某 SPEC 的 `.spec.yaml` 含非空 `title`
- **THEN** 该检查通过，晋升其余流程与改动前一致（不因 title 长度/内容拦截）
