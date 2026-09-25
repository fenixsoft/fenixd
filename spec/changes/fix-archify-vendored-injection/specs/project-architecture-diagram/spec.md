# project-architecture-diagram — 修改：archify 改为 vendored 依赖 + 提示词注入

> 对既有能力 `project-architecture-diagram`（`spec/changes/add-project-architecture-tab/`
> specs/）的增量修改。其余需求（页签与空态、刷新触发、图形态契约、存储与 API 下发、
> 生命周期治理）不变，本文件不再重复。

## MODIFIED Requirements

### Requirement: archify skill 可用性保障

archify skill MUST 以 **vendored 形式随本仓库分发**（`vendor/archify/`，含 SKILL.md 与
其指引引用的伴生文件 schemas/、examples/、references/、renderers/、bin/、scripts/、
assets/ 等，并保留上游 LICENSE 与 THIRD_PARTY_NOTICES；溯源与升级方法见
`vendor/archify/VENDORED.md`）。spawn 前 MUST 校验 vendored 包完整性
（`SKILL.md` 存在且非空）；缺失或为空时本次生成 MUST 判 `failed`，错误信息 MUST 注明
vendored 包缺件属部署损坏，且 MUST NOT 触发任何安装动作。生成提示词 MUST 注入
SKILL.md 指引原文并给出包根绝对路径（指引中出现的相对路径均相对包根解析；
`node bin/archify.mjs` 校验为本地执行、无网络依赖）。生成链路 MUST NOT 执行任何
联网安装（含 `npx skills add`），MUST NOT 依赖用户环境已安装的 skill 或
`$CLAUDE_CONFIG_DIR`/`~/.claude` 下的任何路径。

#### Scenario: 提示词注入 SKILL.md 原文与包根路径

- **WHEN** 后台组装生成提示词
- **THEN** 提示词文本包含 vendored SKILL.md 指引原文（或其可判定特征段）与
  `vendor/archify` 包根绝对路径，且提示词与本次生成的全部子进程命令中均不含
  `npx skills add` 安装指令

#### Scenario: vendored 包缺件判失败（部署损坏文案）

- **WHEN** `vendor/archify/SKILL.md` 缺失或为空时用户点击「刷新架构图」
- **THEN** 状态判 `failed`，错误信息注明 vendored 包缺件属部署损坏（提示对照
  `vendor/archify/VENDORED.md` 恢复），未发起任何安装命令

#### Scenario: 生成链路零联网安装

- **WHEN** 生成被受理并进入后台执行（含 skill 就绪性检查阶段）
- **THEN** 期间派生的唯一外部进程是 claude 本身（测试以 fake Popen 断言收到的全部
  命令均为 claude，无 npx 等其他进程）

#### Scenario: 上游许可声明随包保留

- **WHEN** 检查 vendored 包目录
- **THEN** `LICENSE` 与 `THIRD_PARTY_NOTICES.md` 在位，`VENDORED.md` 记录上游仓库、
  快照 commit、许可与剔除项（`test/`）
