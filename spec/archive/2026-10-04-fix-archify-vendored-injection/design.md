# Design: fix-archify-vendored-injection

## Context

`add-project-architecture-tab` 已上线（pushed，合并 `7a885213`），实测生成失败，错误
文案「archify skill 自动安装超时（>120s），请人工执行后重试」——原 design D4 的
「缺失自动 `npx skills add`」把生成可用性押在生成时刻的外网可达性上，daemon 环境
无代理时必然超时；且全局安装污染用户环境。用户定调三点：本机下载完成、包作为工程
依赖随库分发、skill 不装用户环境而以提示词注入。

上游实测：archify v2.17（commit `9e35d2b`，MIT， Copyright tt-a1i / Cocoon AI），
SKILL.md 16KB，生成期按指引读取 `schemas/` / `examples/` / `references/` /
`renderers/` 伴生文件并用 `node bin/archify.mjs validate` 做本地校验——**必须整包
分发**，只注入 SKILL.md 文本不够。SKILL.md 对 test/benchmarks 明示「生成流程不读」，
`test/`（2.1MB）为上游自测，可剔除。

## Goals / Non-Goals

**Goals**

- 生成链路零联网安装、零用户环境依赖；skill 来源唯一化为 vendored 包。
- 失败模式从「网络超时需人工装」变为「部署损坏需恢复包」（正常部署下不应出现）。

**Non-Goals**

- 不改前端、不改产物契约/状态机/单飞/超时治理（原 spec 其余需求不动）。
- 不做 vendored 包自动升级（升级 = 手工整包替换 + 更新 VENDORED.md，见该文件）。

## Decisions

### D1. vendored 落位 `vendor/archify/`，由立项会话直接落盘提交

用户明确「你在本机完成下载」——本次立项会话已克隆上游（`/tmp/archify-clone`，depth 1）
并整包复制入库（剔除 `test/`，附 `VENDORED.md` 溯源表），commit `4e03cd2f`。该目录
因此**不是**本 SPEC 的交付物（实现分支自 main 分叉时天然可见），SPEC 声明段以
`kind: reference` 审计。备选「由实现 Agent 在 worktree 内下载」被否：恰是该路径的
网络不可靠性导致了本次事故。

### D2. 仓库根定位用 `Path(__file__).resolve().parents[3]`

`architecture_routes.py` 位于 `<repo>/core/dashboard/routes/`，`parents[3]` 即仓库根，
脱离 daemon 进程 cwd 依赖（worktree 内跑单测同样成立）。

### D3. 完整性检查替代安装：SKILL.md 存在且非空

`_vendored_skill_root()` 返回包根；`_skill_ready()` 单点校验 `SKILL.md` 存在且非空。
缺失/为空 → `failed`，错误文案注明「vendored 包缺件属部署损坏，对照 vendor/archify/
VENDORED.md 恢复」。不再有安装限时、重试、人工命令指引。

### D4. 提示词注入：SKILL.md 原文 + 包根绝对路径

`_build_prompt()` 在既有五项形态约束/输出路径/marker 协议之外，前置注入：(a) SKILL.md
指引原文（16KB，一次性任务，token 成本可接受）；(b) 包根绝对路径并注明「指引中相对
路径均相对该目录，可用 `node bin/archify.mjs validate …` 做本地校验（无网络）」。
删除原文案「请使用 archify skill」（其隐含依赖环境已装 skill）。claude 进程 cwd=
目标项目根（不变），读 vendored 包走绝对路径（bypassPermissions 读任意路径可行）。

### D5. 删除物清单

`SKILL_INSTALL_TIMEOUT_SECONDS`、`ARCHIFY_INSTALL_CMD`、`ARCHIFY_INSTALL_CMD_TEXT`、
`_archify_skill_paths()`、`_skill_installed()`、`_ensure_archify_skill()` 全部移除；
对应 docstring/注释同步。测试侧删除「安装超时/安装失败文案」两类用例，新增
「vendored 缺件 → failed 部署文案」「prompt 含注入特征与包根路径」「fake Popen 断言
全程唯一外部进程为 claude」三类。

## Risks / Trade-offs

- [vendored 快照与上游漂移] → VENDORED.md 固化溯源 commit 与整包替换升级法；禁止只换
  SKILL.md（指引与 schemas/examples 版本耦合）。
- [注入增大 prompt ~16KB] → 一次性手动触发任务，成本可接受；换取零网络依赖。
- [claude 读 vendored 伴生文件依赖指引遵从] → 注入原文即原始 skill 语义；产物权威判定
  链（退出码→文件→特征→组件数）不变，不达标仍 failed，可重试。
- [MIT 合规] → LICENSE 与 THIRD_PARTY_NOTICES.md 随包保留 + VENDORED.md 溯源，满足
  许可条款。

## Migration Plan

vendor 包已入库（先于 SPEC 注册）；实现仅改单文件 + 测试 + 文档，回滚 = revert 实现提交
（vendor 目录无副作用可留存）。后端改动需 daemon 重启生效（既有约定，重启由 supervisor
信号完成，非本 SPEC 任务）。

## Open Questions

无（fast-track / 立即执行已确认；vendored 范围剔除上游 test/ 已定为工程决策并记录于
VENDORED.md）。
