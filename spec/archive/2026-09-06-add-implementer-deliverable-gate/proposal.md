# Proposal: add-implementer-deliverable-gate

## Why

实现 agent 会在核心交付物缺失的情况下「成功」收工：v2-config-page 首次实现未创建 `config.json` 页面文件即声明完成，导致 0/11 验证全败，白烧一次 10M+ input 的实现 run + 整轮验证 + 整轮修复（复盘改进点 1）。根因是收工判定只看 agent 自述成功，没有廉价的交付物完整性校验；且实现 agent 无法自测 worktree 页面（worktree-test-server 已另行解决环境问题，本 SPEC 解决判定问题）。

## What Changes

- 实现 run 收工时增加**交付物存在性守卫**：从 tasks.md / proposal.md 提取声明的交付文件路径清单，逐一校验在 worktree 中存在
- 清单有缺件 → run 判定为失败收工，不 merge、不推进状态，按既有重试路径重派（error 注明缺件清单，供下轮 agent 精准补齐）
- 提取规则保守：只校验代码块/反引号/明确路径语法中声明的 `core/**`、`tests/**`、`.fenix/**` 路径，不做语义级校验；无任何可提取路径的 SPEC 跳过守卫（向后兼容）

## Capabilities

### New Capabilities
- `implementer-deliverable-gate`: 实现 run 收工的交付物存在性守卫（提取、校验、缺件失败处置）

### Modified Capabilities

（无——不改验证链与状态机，只在实现收工判定处加一道廉价前置闸门）
