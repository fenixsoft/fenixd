# push-credential-environment Specification

## ADDED Requirements

### Requirement: 推送 git 子进程环境单源解析与显式注入

系统 SHALL 提供单一解析器（`core/git_env.py`）为推送 git 子进程解析运行环境：HOME 依次取 daemon 进程 env 的非空 `HOME` → `pwd.getpwuid(os.getuid()).pw_dir` → 配置 `pm.push.credential_home`（可选覆盖）；三级皆不可用时 MUST NOT 注入 HOME（行为回退现状）且不抛异常。`_git_push_ref` 执行 git push 时 MUST 以解析器产出的显式 `env=` 运行子进程，MUST NOT 裸继承 daemon 进程环境。

#### Scenario: daemon 环境无 HOME 时凭证文件仍可达
- **WHEN** daemon 进程 env 不含 `HOME`，宿主 passwd 目录为 `/root`，且 `/root/.git-credentials` 在场
- **THEN** git push 子进程以显式 env（HOME=/root）运行，凭证经 credential helper 文件解析成功，推送成功且日志无 `could not read Username` / `$HOME not set`

#### Scenario: 三级解析全空时安全回退
- **WHEN** daemon env 无 HOME、pwd 解析失败、配置未设 `pm.push.credential_home`
- **THEN** 解析器返回无 HOME 的 env 且不抛异常，git push 照原样执行（凭证仅剩 URL 内嵌腿），启动自检就此状态发 WARNING 告警

### Requirement: 凭证文件兜底通道

系统 SHALL 在 git push 命令追加显式 credential helper 参数（`-c credential.helper=store --file=<abs>`）作为凭证第二通道：路径默认＝解析后 HOME 下的 `.git-credentials`，可经 `pm.push.credential_file` 覆盖；该解析路径**不存在**时 MUST NOT 追加该参数；配置显式置空字符串时 MUST 关断兜底。URL 内嵌 token 通道与 helper 通道并存兼容。

#### Scenario: 内嵌 token 吊销后凭证文件兜底
- **WHEN** remote URL 内嵌 token 已失效（git 报 Authentication failed），但解析后凭证文件在场且含有效凭证
- **THEN** git 经显式 credential helper 取得凭证，同一次退避续推或人工重推成功，无需人工改写 remote URL

#### Scenario: 凭证文件缺席不产生假象
- **WHEN** 解析后的凭证文件路径不存在且配置未指定 `pm.push.credential_file`
- **THEN** git 命令不含 credential helper 参数，不静默创建空凭证文件，凭证判定回落单腿（URL）并计入启动自检告警

### Requirement: 承载层 HOME 基线

`capture_env_candidate` 捕获 env 候选稿时 SHALL 检查候选稿是否含非空 `HOME`：缺失则以解析器单源补 `HOME=<resolved>` 并按 PATH 追加同款格式注释留痕（补齐清单与原因）；候选稿已含 HOME 时产物 MUST 与无此机制时逐字节一致。`render_project_unit` 渲染的 unit SHALL 含 `Environment=HOME=<resolved>` 保底行——EnvironmentFile 缺席或缺 HOME 键时 daemon 仍带 HOME 启动；env 文件在场且含 HOME 时其值照常覆盖保底行。迁移摘要 SHALL 输出 HOME 卫生结论（「完整」或「补齐 <值>」）。

#### Scenario: 候选稿缺 HOME 时补齐留痕
- **WHEN** 捕获源进程 env 无 HOME 键
- **THEN** env 候选稿含 `HOME=<resolved>` 且带补齐注释留痕，迁移摘要显示 HOME 补齐结论

#### Scenario: 候选稿已含 HOME 时产物逐字节不变
- **WHEN** 捕获源进程 env 已含非空 HOME
- **THEN** env 候选稿产物与无 HOME 基线机制时逐字节一致（无追加注释）

### Requirement: 启动凭证自检告警

daemon 启动自检链 SHALL 增加推送凭证探测（纯本地，不做网络探测）：解析 HOME 是否为存在目录、解析后凭证文件是否在场、任一 remote URL 是否含内嵌凭证；双腿（URL 内嵌凭证 + 凭证文件）皆缺或 HOME 解析失败时发 WARNING 级自检告警。探测 MUST fail-open：任何探测异常只记日志，MUST NOT 阻断 daemon 启动或改变派发行为。

#### Scenario: 双腿皆缺时启动告警
- **WHEN** daemon 启动且解析 HOME 失败（或凭证文件不在场），且全部 remote URL 无内嵌凭证
- **THEN** 自检输出一条 WARNING 告警（含双腿皆缺的归因与人工处置指引），daemon 正常启动，派发与推送行为不被该告警阻断

#### Scenario: 单腿可用时不告警
- **WHEN** remote URL 含内嵌凭证（凭证文件缺席），或凭证文件在场（URL 无内嵌凭证）
- **THEN** 启动自检不发凭证告警（单腿可用属可运行状态，不再制造噪音）
