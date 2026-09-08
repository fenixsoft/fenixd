# draft-promotion-gate — SPEC 草稿自动晋升门控

## ADDED Requirements

### Requirement: 草稿自动晋升配置键
系统 SHALL 提供配置键 `gates.auto_promote_draft`（bool），缺省值 MUST 为 `true`（保持现有自动晋升行为）。配置校验 SHALL 拒绝非布尔值并在加载时报错。该键 MUST 纳入 Dashboard 受管配置键白名单，支持经设置页读写与配置热更新（30s mtime 原地重载）。

#### Scenario: 缺省值为 true
- **WHEN** 配置文件中不存在 `gates.auto_promote_draft` 键
- **THEN** getter 返回 `true`，自动晋升行为与引入该键之前完全一致

#### Scenario: 显式关闭
- **WHEN** 配置文件中 `gates.auto_promote_draft` 为 `false`
- **THEN** getter 返回 `false`，自动晋升被关闭

#### Scenario: 非法值被拒
- **WHEN** 配置文件中 `gates.auto_promote_draft` 为字符串 `"yes"` 或其它非布尔值
- **THEN** 配置加载校验失败并给出明确错误信息，指出合法取值为布尔

#### Scenario: 设置页读写与热更新
- **WHEN** 用户在设置页审批页签切换该开关并保存
- **THEN** 值持久化到对应配置层（用户级/项目级按现有受管键规则），且 daemon 在热更新窗口内感知新值，无需重启

### Requirement: 自动晋升闸口
PM Engine 的 drafted → ready 晋升入口 SHALL 检查 `gates.auto_promote_draft`：
- 为 `true`（或缺省）时，晋升链行为 MUST 与引入该键之前完全一致（软化 + 声明 lint + tasks 可解析性 lint + transition ready + 派发）。
- 为 `false` 时，SHALL 不执行软化、不执行 lint、不 transition、不派发；MUST NOT 向 STATE 写 error（等待人工放行是设计行为而非故障）；SHALL 记 info 日志说明该 SPEC 停留 drafted 等待人工放行。

闸口 MUST 覆盖全部 drafted 晋升触发路径：`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入。

#### Scenario: 关闭后新注册 SPEC 停留草稿
- **WHEN** `gates.auto_promote_draft` 为 `false` 且新 SPEC 注册为 drafted（触发 `spec_drafted` 事件）
- **THEN** SPEC 状态保持 drafted，无 implementer 派发，STATE 无 error 写入，日志含「等待人工放行」语义

#### Scenario: 关闭后 start_after 到期仍停留
- **WHEN** `gates.auto_promote_draft` 为 `false` 且某 drafted SPEC 的 `start_after` 到期
- **THEN** 该 SPEC 不被晋升与派发，状态保持 drafted

#### Scenario: full_scan recovery 遵守闸口
- **WHEN** `gates.auto_promote_draft` 为 `false` 且 full_scan recovery 扫描到 drafted SPEC 并 re-trigger promote
- **THEN** 闸口生效，SPEC 停留 drafted（不产生晋升与派发）

#### Scenario: 关闭期间 lint 不提前暴露不回滚
- **WHEN** 自动晋升关闭期间某 drafted SPEC 的声明段存在 lint 违规
- **THEN** 系统不在 drafted 阶段执行晋升 lint（无 error 写入）；违规在人工放行时按 manual-spec-promotion 能力的规则拦截

#### Scenario: 重新开启后存量草稿恢复自动晋升
- **WHEN** `gates.auto_promote_draft` 从 `false` 改回 `true`，且存在停留 drafted 的存量 SPEC
- **THEN** 在下一次 full_scan recovery（或新的 drafted 触发）时，存量 SPEC 走完整晋升链自动晋升，无需人工逐个干预

### Requirement: 设置页审批页签草稿晋升开关
Dashboard 设置页「审批」页签 SHALL 新增「草稿自动晋升」开关控件，MUST 位于现有审批模式（approve_mode）设置项上方。开关 SHALL 附带说明文字，说明关闭后 SPEC 停留草稿态供人工阅读、需在项目页手动放行。

#### Scenario: 开关位于审批模式上方
- **WHEN** 用户打开设置页审批页签
- **THEN** 「草稿自动晋升」开关渲染在审批模式（manual/auto）设置项上方

#### Scenario: 开关反映当前配置
- **WHEN** 当前 `gates.auto_promote_draft` 为 `false`
- **THEN** 页面加载后开关显示为关闭态

#### Scenario: 保存生效
- **WHEN** 用户切换开关并点击保存
- **THEN** 配置写入成功且页面无错误提示；重新进入页面后开关状态与配置一致

### Requirement: 配置与治理文档同步
docs 目录 SHALL 同步本次变更：配置文档（docs/help/08-config.md）SHALL 增补 `gates.auto_promote_draft` 键的说明（取值/缺省/热更新属性）；治理文档（docs/help/06-governance.md）SHALL 增补草稿人工放行流程说明。

#### Scenario: 配置文档含新键
- **WHEN** 查阅 docs/help/08-config.md 的 gates 配置说明
- **THEN** 包含 `auto_promote_draft` 条目，注明 bool 类型、缺省 true、热更新属性

#### Scenario: 治理文档含人工放行流程
- **WHEN** 查阅 docs/help/06-governance.md 的 SPEC 生命周期/审批说明
- **THEN** 包含「关闭自动晋升后如何人工放行（项目页按钮 / CLI promote）」的流程说明
