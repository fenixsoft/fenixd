## ADDED Requirements

### Requirement: 品牌经 context 外部投影

claude-msg 对话组件的消息头标签与头像图标 MUST 经 `HarnessBrand` context 取得（`{ name, Logo }`），组件内 MUST NOT 出现字面 `'Claude'` 标签或无条件 `ClaudeLogo` 渲染。context 缺省值 MUST 为 Claude 品牌——未注入 Provider 的使用点行为与现状一致。

#### Scenario: 缺省品牌等于现状

- **WHEN** 不注入 Provider 渲染消息列表
- **THEN** 消息头标签显示 `Claude`、头像为 ClaudeLogo，与改造前渲染结果一致

### Requirement: run 维度按 harness 注入

run 视图（RunRecordModal/AdminRunModal）MUST 从 run meta 读取 `harness` 字段并注入对应品牌；run meta 的 harness 来自 run_metrics 旁路行的新增 `harness` 键（runner 以该 run 派发时确定的 adapter.name 写入，并发 run 不串号；未装配 adapter 的提前终态路径省略该键）。

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

DshLogo MUST 以官方资产渲染（本 change `assets/dsh-mark.svg`，源自 deepseek.com/harness/favicon.svg），填充 MUST 固化为其基础品牌蓝 `#4D6BFE` 且 MUST NOT 携带 `prefers-color-scheme` 媒体查询——dashboard 固定浅色主题，OS 暗色偏好的白色变体在浅色界面同色消失（应用引入暗色主题时再恢复自适应），aria-label 为 `dsh`。

#### Scenario: 明暗两态可见

- **WHEN** 浅色界面渲染 dsh 消息头像（含以 prefers-color-scheme:dark 仿真 OS 暗色偏好的环境）
- **THEN** 图标恒为基础品牌蓝、在界面底色上可见（非同色消失）
