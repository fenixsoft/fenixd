# verify-evidence-placement 规格

## ADDED Requirements

### Requirement: 验证证据落位契约
验证/核查链 SHALL 把原始证据统一落 .fenix/verify-evidence/<spec>/（被消费项目忽略规则覆盖的路径），验证契约 SHALL 提供可覆盖的 evidence_dir 字段（缺省上述路径）。

#### Scenario: 证据落位
- **WHEN** 验证 run 产生原始证据文件（扫描结果/转储/探针产物）
- **THEN** 默认落 .fenix/verify-evidence/<spec>/，主树根不再出现证据散件，报告仅引用相对路径

#### Scenario: 契约覆盖
- **WHEN** 验证契约显式声明 evidence_dir
- **THEN** 以契约值为准，缺省回退 .fenix/verify-evidence/<spec>/

### Requirement: untracked 散件盘点信号
maintree 盘点 SHALL 增补 untracked 散件信号（只告警不处置）：entry 级判定、同指纹一次性、指纹消失自动复位，豁免 .fenix/ negation 放行项与已 ignore 路径。

#### Scenario: untracked 散件滞留
- **WHEN** 主树出现超阈值的 untracked 散件且跨宽限周期滞留
- **THEN** 发一次性告警列明路径，不自动处置；指纹消失后状态自动复位

#### Scenario: 有意放行项不误报
- **WHEN** untracked 条目位于 .fenix/ 内被显式 negation 放行（如 .fenix/verify.yaml）或已被 ignore 规则覆盖
- **THEN** 不产生告警