## ADDED Requirements

### Requirement: 三个调优参数的配置读取器

系统 SHALL 新增三个 `ConfigLoader` 读取器，读取合并后配置（用户级默认 + 项目级覆盖由既有 `resolve_config` 深合并完成）中的 `verify.impl_code_review_timeout_sec` / `verify.impl_code_review_concurrency` / `verify.impl_code_review_effort`。

- 三者 MUST 遵循同型回退语义：键缺失、`verify` 节缺失或非 dict、类型非法、超出合法区间时，一律返回缺省值（fail-open，脏值不中断派发）。
- `timeout_sec`：缺省 `600`；合法区间为**正整数**，非 int / bool 混入 / ≤0 / 非数字字符串一律回退缺省。
- `concurrency`：缺省 `2`；合法区间为**正整数**，非 int / ≤0 一律回退缺省。
- `effort`：缺省 `"low"`；合法值为 `"low"` / `"medium"` / `"high"` 三者之一，其余取值一律回退缺省。
- 三个读取器 MUST 各自独立，互不影响（例：`effort` 非法不应连带使 `timeout_sec` 回退）。

#### Scenario: 键缺失时取缺省
- **WHEN** 合并配置中 `verify` 节存在但不含三个新键
- **THEN** `get_impl_code_review_timeout_sec` 返回 `600`、`get_impl_code_review_concurrency` 返回 `2`、`get_impl_code_review_effort` 返回 `"low"`

#### Scenario: 非法值回退缺省
- **WHEN** `verify.impl_code_review_timeout_sec` 为 `"abc"`、`verify.impl_code_review_concurrency` 为 `0`、`verify.impl_code_review_effort` 为 `"extreme"`
- **THEN** 三个读取器分别返回 `600` / `2` / `"low"`，且不抛异常

#### Scenario: 合法值透传
- **WHEN** 三个键分别为 `900` / `4` / `"high"`
- **THEN** 三个读取器分别返回 `900` / `4` / `"high"`

#### Scenario: 项目级覆盖用户级
- **WHEN** 合并后结果为 `verify.impl_code_review_effort = "medium"`（项目级覆盖了用户级的 `"low"`）
- **THEN** 读取器返回 `"medium"`

### Requirement: run 级 ocr 超时注入

系统 SHALL 在写 run 级 ocr provider 配置时，把配置的 `timeout_sec` 写入该 provider 条目。

- `runner._write_run_ocr_config` 写入的 `custom_providers.fenix-impl` 条目 MUST 含 `timeout_sec`，取值为 `get_impl_code_review_timeout_sec` 解析结果。
- 该注入 MUST 与既有 `api_key` / `url` / `protocol` / `model` 同批原子写入（tempfile + `os.replace`），不新增独立写路径。
- 写入失败 MUST 沿用既有降级：记 WARNING 并返回 `None`，不阻塞 run 派发。

#### Scenario: 注入生效
- **WHEN** 开关 `verify.impl_code_review` 为 true 且 `verify.impl_code_review_timeout_sec = 900`
- **THEN** run 级 `ocrcfg/.opencodereview/config.json` 的 `custom_providers["fenix-impl"]["timeout_sec"]` 值为 `900`

#### Scenario: 缺省注入
- **WHEN** 开关为 true 且未配置 `timeout_sec`
- **THEN** 落盘配置中 `timeout_sec` 值为 `600`

#### Scenario: 写失败降级
- **WHEN** 落盘过程抛 `OSError`
- **THEN** 函数返回 `None`、记 WARNING，run 照常派发（审查环境缺失不影响 run 主体）

### Requirement: 提示词承载并发与力度

系统 SHALL 在收尾代码质量审查提示词段的命令示例中注入配置的并发与力度参数。

- 命令示例 MUST 含 `--concurrency <concurrency>` 与 `--effort <effort>`，取值来自对应读取器。
- 提示词 MUST NOT 含 `--max-tokens-budget`（按 token 硬中止会令多数文件判 failed，致审查覆盖残缺）。
- 开关关闭时该段零注入（返回空串），不变。

#### Scenario: 注入命令参数
- **WHEN** 开关为 true、`concurrency = 3`、`effort = "medium"`
- **THEN** 注入段命令示例含 `--concurrency 3` 与 `--effort medium`

#### Scenario: 缺省值注入
- **WHEN** 开关为 true 且未配置这两个键
- **THEN** 注入段命令示例含 `--concurrency 2` 与 `--effort low`

#### Scenario: 开关关闭零注入
- **WHEN** `verify.impl_code_review` 为 false
- **THEN** 提示词不含"收尾代码质量审查"段，逐字节与未开启时一致

### Requirement: 质量页签的三项参数编辑

Dashboard 设置页「质量」页签 SHALL 提供三个新参数的读取回显与可视化编辑。

- `impl_code_review_timeout_sec` MUST 为数字输入（正整数，附单位"秒"），回显缺省 `600`。
- `impl_code_review_concurrency` MUST 为数字输入（正整数），回显缺省 `2`。
- `impl_code_review_effort` MUST 为下拉选择（`low` / `medium` / `high`），回显缺省 `low`。
- 保存 MUST 序列化三个键写入项目级/用户级配置，遵循既有作用域与保存链路，MUST NOT 覆写未在表单中出现的其它配置键。
- 三键 MUST 登记进设置页受管键清单（受 sources 标注与合并回显管辖），与既有 `verify.impl_code_review` 同卡呈现。

#### Scenario: 缺省回显
- **WHEN** 配置中不含三个新键，用户打开质量页签
- **THEN** 超时显示 `600`、并发显示 `2`、力度显示 `low`

#### Scenario: 保存后回读
- **WHEN** 用户把超时改为 `900`、并发改为 `4`、力度改为 `high` 并保存
- **THEN** 落盘配置含这三个值，重新打开页签时回显 `900` / `4` / `high`

#### Scenario: 不覆写其它键
- **WHEN** 用户只修改力度并保存，而配置中另有 `verify.deps_mode = "hardlink"`
- **THEN** 保存后 `verify.deps_mode` 值不变

### Requirement: 配置模板与文档同步

系统 SHALL 在配置模板与帮助文档中登记三个新键。

- `.fenix/config.template.yaml` 的 `verify` 段 MUST 含三键及注释（语义 + 缺省值）。
- `docs/help/09-config.md` MUST 文档化三键的语义、缺省值与合法取值范围。
- `docs/help/08-dashboard.md` MUST 描述质量页签新增的三项设置。

#### Scenario: 模板含三键
- **WHEN** 检查 `.fenix/config.template.yaml` 的 `verify` 段
- **THEN** 含 `impl_code_review_timeout_sec` / `impl_code_review_concurrency` / `impl_code_review_effort`，且缺省值分别为 `600` / `2` / `low`

#### Scenario: 文档可查
- **WHEN** 用户查阅 `docs/help/09-config.md` 的 `verify` 节
- **THEN** 能查到三个键的语义、缺省与合法值说明
