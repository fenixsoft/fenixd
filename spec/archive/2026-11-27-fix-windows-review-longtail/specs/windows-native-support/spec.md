# Delta Spec: windows-native-support

> 归属变更：fix-windows-review-longtail（Windows 部署评审长尾 C3/C4）
> 基线：spec/changes/windows-native-support/specs/windows-native-support/spec.md

## ADDED Requirements

### Requirement: 安装链可观测性（首装零噪音与编码安全）

win32 安装链（`install_unit` 等）的日志输出 MUST 满足部署可判读性：

- 正常首装路径（服务未安装 → 走安装决策）MUST NOT 产生 warning 级及以上日志信号；
  「未安装」是预期态，至多 debug 级留痕。warning 级信号 MUST 仅用于拿到瞬时失败证据
  的场景（如 sc query 超时、或退出码非「1060 服务不存在」的失败后的纠偏路径）。
- win32 平台日志写 stderr MUST 编码安全：在 GBK/cp1252 等受限控制台编码下，
  含中文的日志消息 MUST 以替换符降级输出，MUST NOT 以 `UnicodeEncodeError`
  traceback 形态混入捕获流（该形态会被部署者误判为故障）。
- 本要求不改变 `install_unit` 返回 JSON 形状（`ok/error/already/unit`）、
  服务安装语义与 Linux 后端行为。

#### Scenario: 干净机器首装路径零 warning

- **WHEN** 在未安装过服务（`_service_state` 因 sc query 退出码 1060「服务不存在」
  返回 None，且无其他瞬时失败证据）的项目根调用 `install_unit`
- **THEN** 返回 `{"ok": true, ...}` 且全程无 warning 级及以上日志输出（至多 debug 留痕）

#### Scenario: GBK 控制台下日志编码安全

- **WHEN** 进程 stderr 编码为 GBK/cp1252 且日志消息含中文（如「按未安装走安装决策」）
- **THEN** 日志以替换符（`?`/U+FFFD）降级写出，stderr 中不出现 `UnicodeEncodeError`
  traceback

#### Scenario: subprocess 输出解码加固（GBK sc.exe 输出不再崩）

- **WHEN** `core/platform/win32.py` 中任何 `capture_output` 的 `subprocess.run`
  在 GBK 控制台+提权 PS5.1 环境读 sc.exe/nssm 输出（含 GBK 双字节序列）
- **THEN** 解码以 `errors="replace"` 降级，不抛 `UnicodeDecodeError`、读线程不崩、
  也不被归一成「状态查询无响应」假告警（确定性发生场景的下限保证）

#### Scenario: Linux 行为逐位不变

- **WHEN** 在 Linux 上运行全量测试（`tests/test_platform_pal.py` + 既有回归面）
- **THEN** 零失败、零新增豁免（Linux 零变化硬约束；`core/platform/linux.py` 不改）

### Requirement: skill 部署文档双平台命令口径

`skills/*/SKILL.md` 作为部署者与 agent 的执行说明书，命令口径 MUST 双平台可执行：

- 每个 skill MUST 含统一的「Windows 命令换算」校准注记：文内 `python3` 在 Windows
  上一律换算为 `py -3`（其余 Unix 形态命令按各节既有注记换算）。
- 校准注记 MUST 位于命令首次出现之前的位置，使 agent 读取命令前已获得换算规则。
- 本要求为文档口径约束，MUST NOT 改变 skill 的触发条件、流程语义或任何代码。

#### Scenario: skill 含换算校准注记

- **WHEN** 检查 8 个 `skills/*/SKILL.md`（fenix-approve/archive/dashboard/new/
  process/prototype/setup/status）
- **THEN** 每个 SKILL.md 在可复制命令出现前含「Windows 命令换算」注记
  （`python3` → `py -3`）

#### Scenario: 注记不改变 skill 语义

- **WHEN** 对比注记加入前后的 skill 文件
- **THEN** 触发描述、流程步骤、判定规则逐字不变（仅新增注记与必要的高频命令行内双写）

### Requirement: 制品与骨架完整性（fail-fast）

fenixd 制品形态（GitHub Release 解压即用）与部署脚本 MUST 保证 fenix-init 全读面
存在，且所有完整性校验 MUST 以硬失败收口，禁止静默降级：

- `fenix-init` MUST 在创建任何目录/文件**之前**前置校验骨架全读面
  （`.fenix/config.template.yaml`、`.fenix/config.user.template.yaml`、
  `FENIX_LINKS`、`AGENT_LINKS`、`templates/`），任一缺失即退出非 0 并输出缺失明细
  （v0.1.0 制品缺模板时 fenix-init 在 mkdir 后才崩、留下半成品骨架——禁止复现）。
- `fenix-init` MUST 提供 `--version`（输出制品版本号，部署验证门可机器判读）。
- 骨架清单（`FENIX_LINKS`）MUST NOT 引用源码根不存在的文件（`__init__.py` 悬空引用移除）。
- `install.ps1` 的完整性自检 MUST 硬失败：部署面/模板缺失时退出码非 0
  （v0.1.0 为 WARN + exit 0 静默降级，导致部署"看似成功"实际缺骨架）。

#### Scenario: 制品缺模板时 fenix-init 前置硬失败

- **WHEN** 在缺 `.fenix/config.template.yaml` 的部署面运行 `fenix-init . --name demo --type web`
- **THEN** 进程在创建任何目录/文件之前退出非 0，输出含缺失文件路径的明细，
  工作目录不留半成品骨架

#### Scenario: --version 机器可判读

- **WHEN** 运行 `fenix-init --version`
- **THEN** 输出版本号（与制品 VERSION 一致）且退出 0

#### Scenario: install.ps1 完整性自检硬失败

- **WHEN** 部署面缺失任一 fenix-init 硬读面文件时运行 `install.ps1`
- **THEN** 进程退出码非 0 并报缺失清单（不以 WARN + exit 0 收场）
