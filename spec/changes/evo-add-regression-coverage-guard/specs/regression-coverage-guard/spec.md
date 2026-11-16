# prepare 装配与回归白名单一致性预检

## ADDED Requirements

### Requirement: prepare↔regression 一致性预检

契约解析/校验 SHALL 对 prepare 段 install/build 步骤声明的包目录集合与 regression 段 cmd 文本引用集做交叉比对；prepare 装配了某包而 regression 全文无该包引用时，SHALL 发 `regression_coverage_gap` WARNING 并附缺口包清单与 regression 段行号指引，SHALL NOT 阻断契约加载。

#### Scenario: 半收编契约发出缺口告警

- **WHEN** 契约 prepare 段含 `pnpm --dir fenix-dsh-session-advanced-search install`，而 regression cmd 全文不含该包名（对照 dsh-plugins 11-12 扩编实测形态）
- **THEN** 解析/校验时发出 regression_coverage_gap WARNING，缺口清单含该包名，加载不被阻断

#### Scenario: 对称契约零输出

- **WHEN** prepare 装配的每个包目录都在 regression cmd 中被引用（对照 cc-import/dashboard-bridge 现状）
- **THEN** 无 WARNING 输出，加载行为零变化

#### Scenario: 非包形态契约保守跳过

- **WHEN** prepare 步骤无法识别出包目录形态（如纯 pytest cmd 契约）
- **THEN** 跳过比对，不误报

#### Scenario: regression 段缺省保守跳过

- **WHEN** 契约 prepare 段含 `pnpm --dir <pkg> install` 形态步骤，但 regression 段整体未配置（模板明文合法引导态：分面显示、不派发、零报错）
- **THEN** 跳过比对，不发声——本检查只治「regression 已配置但收编不全」，全量缺省归引导态治理面

### Requirement: 模板收编指引

verify_contract_template.yaml 的 regression 段指引 SHALL 载明「新增被测插件进 prepare 时须同步注册 regression install+test 条目」，prepare 段指引 SHALL 载明对称提示。

#### Scenario: 作者当下可见

- **WHEN** 按 template 起草/扩编契约
- **THEN** regression 与 prepare 两段指引均含同步注册提示