# Proposal: fix-archify-vendored-injection

## Why

实测生成失败：运行时 `npx skills add tt-a1i/archify -g` 自动安装超时（>120s）——现行设计把
「能否生成」押在生成时刻的外网可达性上，而该时刻恰恰不可控（daemon 环境无代理）。同时把
skill 装进用户全局环境（`~/.claude/skills/`）是隐藏的全局副作用。用户定调：**archify 包
本机下载后作为本工程依赖随库分发，生成时不安装 skill，改为把 skill 指引原文直接注入
claude 提示词**。

## What Changes

- **archify 包已 vendored 入库**（本次立项会话完成，commit `4e03cd2f`）：上游 v2.17
  （commit `9e35d2b`，MIT）整体快照至 `vendor/archify/`，剔除上游自测 `test/`，保留
  LICENSE / THIRD_PARTY_NOTICES，溯源与升级方法见 `vendor/archify/VENDORED.md`。
- **删除运行时安装链路**：`architecture_routes.py` 移除 `npx` 安装常量与
  `_archify_skill_paths` / `_skill_installed` / `_ensure_archify_skill` 三函数及 120s
  限时，生成链路不再发起任何联网安装、不依赖用户环境 skill。
- **改为 vendored 完整性检查 + 提示词注入**：spawn 前校验 `vendor/archify/SKILL.md`
  存在且非空（缺失判 failed，注明属部署损坏）；生成提示词注入 SKILL.md 指引原文并给出
  包根绝对路径（指引中相对路径相对包根解析，`node bin/archify.mjs validate` 为本地
  无网校验）。
- **测试与文档同步**：安装失败/超时用例替换为 vendored 缺件 / 注入特征 / 无 npx 进程
  断言；`docs/help/08-dashboard.md` 失败排查段改写。

## Capabilities

### New Capabilities

<!-- 无 -->

### Modified Capabilities

- `project-architecture-diagram`: 「archify skill 可用性保障」需求整体改写——可用性来源
  从「运行时自动安装」改为「vendored 随库分发 + SKILL.md 原文注入提示词」，生成链路
  零联网安装、零用户环境依赖。既有能力 spec 位于
  `spec/changes/add-project-architecture-tab/specs/project-architecture-diagram/spec.md`。

## Impact

- **后端**：`core/dashboard/routes/architecture_routes.py`（删安装链路、加 vendored
  解析与注入）。
- **测试**：`tests/test_dashboard_architecture_api.py`（用例替换）。
- **文档**：`docs/help/08-dashboard.md`（「项目架构」分面两处措辞与失败排查段）。
- **既有引用**：`vendor/archify/`（已入库，非本 SPEC 交付物；实现分支自 main 分叉天然可见）。
- 前端零改动（错误文案经既有 failed 态展示）。
