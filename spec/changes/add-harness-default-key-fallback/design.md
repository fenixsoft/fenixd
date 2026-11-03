# Design: add-harness-default-key-fallback

## Context

- 设计真相源：`docs/superpowers/specs/2026-11-03-escalation-chain-admin-arbiter-design.md`（链语义细则 #6：回落语义对 harness 对称，用户 2026-11-03 裁定）
- 现状：dsh 适配器 `build_spawn_spec` 对 model/baseurl/apikey 三要素逐一预检（`dsh_adapter.py:715-735`），缺任一抛 `DshSpawnConfigError`——2026-11-02 dsh-plugins arbiter run 因此 0.001s/0 tokens 秒败；claude 适配器无此预检（knowledge-distiller 等车道长期无分配工作）
- 原「绝不回退 dsh 默认档」的两条理由（10-09 别名拒识教训、provider 归因）对 claude 回落同样成立且已被用户接受（WARN 观察钩子即为此设），不构成 dsh 单独豁免的依据
- 全局 `agent.harness` 现为 claude；harness 为项目可覆盖项，dsh 形态必须支持

## Goals / Non-Goals

**Goals**

- 两 harness 无分配均可开箱 spawn（对称语义）
- 回落可观测：一次性 WARN + metrics 归因标记
- 显式链形态行为逐字节不变（回归红线）

**Non-Goals**

- 不改动 `agents.models` 配置 schema 与分配面板
- 不实现 dsh profile 默认模型的回读/展示（归因以标记降级表达）
- 不涉及处置链逻辑（属 `add-escalation-chain-admin-arbiter`）

## Decisions

1. **省略 `--patch` 而非写空 patch**：dsh 侧「无 patch=profile 默认档」是 profile 系统原生语义，写空 patch 反而引入「空值渲染」歧义；argv 组装点按 `patch_path is None` 分支。
2. **笔误防护保留**：`env_overrides` 含任一 provider 链键但不含全部三要素时仍报错——区分「无分配（合法回落）」与「配了一半（配置错误）」。
3. **WARN 去重粒度=进程×adapter**：进程级 flag（与 `get_current_adapter` 的锁纪律同型），不做持久化去重——daemon 重启后提醒一次是可接受的观察成本。
4. **归因标记键 `provider_source`**：run metrics context 新键（读侧缺省无此键=显式链），不重载既有 `provider`/`model` 键的语义（对齐「不重载既有枚举」惯例）。

## Risks

- dsh profile 默认模型不可用 → run 失败走既有失败轨（transient/熔断），失败证据含 dsh stderr——可归因，不新增静默面
- 快照测试（`test_harness_claude_snapshot`）锁定 claude 形态——本 SPEC claude 侧仅加 WARN 钩子（日志面），spawn spec 输出不变，快照应零改动；dsh 侧既有显式链用例必须全绿
