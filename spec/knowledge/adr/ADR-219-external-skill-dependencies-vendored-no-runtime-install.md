# ADR-219：外部 skill 依赖一律 vendored 随库分发，运行时零联网安装

date: 2026-10-04
status: accepted

## Context

`add-project-architecture-tab` 上线后实测生成失败：运行时 `npx skills add tt-a1i/archify -g`
自动安装超时（>120s）。原设计把「能否生成」押在生成时刻的外网可达性上，而 daemon 环境
无代理、该时刻恰恰不可控；同时把 skill 装进用户全局环境（`~/.claude/skills/`）是隐藏的
全局副作用。另实测上游 archify 生成期按指引读取 `schemas/`、`examples/`、`references/`、
`renderers/` 等伴生文件并执行 `node bin/archify.mjs validate` 本地校验——只注入 SKILL.md
文本或只分发单文件都不够，必须整包可用。

## Decision

外部 skill/工具类依赖一律以 **vendored 整包随本仓库分发**（`vendor/<name>/`）：含入口
文件与其指引引用的全部伴生文件，保留上游 LICENSE 与 THIRD_PARTY_NOTICES，溯源（上游
仓库、快照 commit、许可、剔除项）与升级方法固化在包内 `VENDORED.md`；升级=手工整包
替换并同步更新该文件，禁止只换单个文件（指引与伴生文件版本耦合）。剔除范围仅限明确
不参与运行的上游内容（如自测 `test/`），并以工程决策记录在 VENDORED.md。

运行时**零联网安装、零用户环境依赖**：生成/执行链路 MUST NOT 发起任何安装命令（含
`npx skills add`）、MUST NOT 读写 `$CLAUDE_CONFIG_DIR`/`~/.claude` 下的 skill 路径。
skill 指引以**提示词注入原文 + 包根绝对路径**交付给一次性 agent（指引中相对路径均相对
包根解析），代替「使用某某 skill」这类隐含环境已装的措辞。

能力可用性不得押在运行时外网可达性上：部署完整性缺失（包/入口文件缺失或为空）属
**部署损坏**，fail-closed 判失败并提示对照 VENDORED.md 恢复，MUST NOT 以联网安装自愈。

vendored 包落库时机先于消费它的 SPEC 实现（由立项/准备会话直接落盘提交），使其不构成
实现 SPEC 的交付物，实现分支自 main 分叉时天然可见。

## Consequences

- 仓库体积增大（剔除上游自测可缓解）；vendored 快照与上游存在漂移，靠 VENDORED.md
  溯源纪律与整包替换升级法约束，不做自动升级。
- 注入指引原文增大一次性任务 prompt 体积（archify 约 16KB），换取生成时刻零网络依赖；
  手动触发的低频任务成本可接受。
- 遵从指引依赖 agent 自律，产物成败仍由产物实况判定链权威裁决（见 ADR-217），不达标
  仍判失败可重试。
- MIT 等许可合规由随包保留 LICENSE / THIRD_PARTY_NOTICES + VENDORED.md 溯源满足。
