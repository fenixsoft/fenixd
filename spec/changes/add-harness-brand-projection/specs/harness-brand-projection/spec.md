## ADDED Requirements

### Requirement: 品牌经 context 外部投影

claude-msg 对话组件的消息头标签与头像图标 MUST 经 `HarnessBrand` context 取得（`{ name, Logo }`），组件内 MUST NOT 出现字面 `'Claude'` 标签或无条件 `ClaudeLogo` 渲染。context 缺省值 MUST 为 Claude 品牌——未注入 Provider 的使用点行为与现状一致。

#### Scenario: 缺省品牌等于现状

- **WHEN** 不注入 Provider 渲染消息列表
- **THEN** 消息头标签显示 `Claude`、头像为 ClaudeLogo，与改造前渲染结果一致

### Requirement: run 维度按 harness 注入

run 视图（RunRecordModal/AdminRunModal）MUST 从 run meta 读取 `harness` 字段并注入对应品牌；run meta 的 harness 来自 run_metrics 旁路行的新增 `harness` 键（runner 以当前 adapter.name 写入）。

#### Scenario: dsh run 显示 dsh 品牌

- **WHEN** 打开一个 harness=dsh 的 run 的对话记录
- **THEN** 消息头标签显示 `dsh`、头像为官方鲸鱼图标（DshLogo，aria-label="dsh"）

#### Scenario: claude run 显示不变

- **WHEN** 打开一个 harness=claude（或无 harness 字段）的 run
- **THEN** 显示 Claude 品牌与 ClaudeLogo，与现状一致

### Requirement: 回退链

run meta 无 harness 字段 MUST 回退 claude 品牌；harness 值无注册品牌时 MUST 回退首字母徽标（圆形底 + 大写首字母），MUST NOT 抛错白屏。

#### Scenario: 未知 harness 回退徽标

- **WHEN** run meta 的 harness 为未注册值（如 `pi`）
- **THEN** 头像渲染 `P` 首字母徽标、标签显示 `pi`，页面正常

### Requirement: dsh 官方图标入库

DshLogo MUST 以官方资产渲染（本 change `assets/dsh-mark.svg`，源自 deepseek.com/harness/favicon.svg），MUST 保留其明暗自适应（亮色黑/暗白/基础品牌蓝），aria-label 为 `dsh`。

#### Scenario: 明暗两态可见

- **WHEN** dashboard 分别以亮色/暗色主题渲染 dsh 消息头像
- **THEN** 两种主题下图标均可见（非同色消失）
