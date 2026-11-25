# 能力规格：cli-message-i18n（CLI 人读输出国际化）

## ADDED Requirements

### Requirement: CLI locale 解析链
CLI 人读输出语言 SHALL 按以下优先级解析：`--lang` 命令行参数 > `FENIX_LANG` 环境变量 > 用户级配置 `general.locale` > 缺省 `zh`；值域白名单为 `zh`/`en`，白名单外值按缺省 `zh` 处理。`core/config.py` SHALL 新增 `general.locale` 配置键（用户级/项目级作用域沿用既有机制，缺省 `zh`）。

#### Scenario: 解析链逐级生效
- **WHEN** 分别单独设置 `--lang en`、仅 `FENIX_LANG=en`、仅配置 `general.locale: en`、四者皆无
- **THEN** CLI 人读输出依次为英文、英文、英文、中文

#### Scenario: 白名单外值回退中文
- **WHEN** `--lang ja` 或 `FENIX_LANG=fr`
- **THEN** CLI 人读输出为中文

### Requirement: CLI 人读输出经目录
`bin/fenix_cli.py` 的人读提示（成功确认、失败拒绝、错误与 lint 违规提示等）SHALL 经消息目录单源输出双语；MUST NOT 改变任何命令的退出码、JSON 机器可读输出（如有）与行为语义。其余 bin 工具本期不强制改造（目录机制就绪即可按需接入）。

#### Scenario: 命令输出双语且行为不变
- **WHEN** 以 `--lang en` 与缺省语言分别执行同一成功命令（如晋升 ready）
- **THEN** 输出分别为英文与中文成功提示，退出码一致

#### Scenario: 失败提示双语
- **WHEN** 以 `--lang en` 执行一个必然失败的命令（如晋升被 lint 拒绝）
- **THEN** 错误提示为英文，退出码与中文档一致

### Requirement: 消息目录跨车道共用
CLI 与后端 SHALL 消费同一消息目录单源模块；同一消息键在不同消费面 SHALL 输出语义一致的双语文本，MUST NOT 出现各自维护的第二份字典。

#### Scenario: 同键同语义跨消费面一致
- **WHEN** 查询同一消息键的 zh/en 文本（经 CLI 路径与经 Dashboard API 路径各一次）
- **THEN** 两消费面返回的文本逐字节一致
