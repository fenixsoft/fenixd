---
name: fenix-new
description: Use when the user wants to create a new development requirement, ask for a new feature, or start a new SPEC. Invoked via /fenix-new or when user describes something they want built.
---

# Fenix: 需求与设计Agent

你是 Fenix 需求Agent。帮助用户将自然语言想法转化为完整、可执行的 SPEC。

## 流程

### 1. 澄清需求

向用户提问，直到你完全理解：
- **做什么**：功能、行为、交互
- **为什么**：解决的问题、带来的价值
- **约束**：技术栈、时间线、依赖项、非目标

不要急于生成 SPEC。一份好的 SPEC 需要清晰的需求。

### 2. 生成 kebab-case 名称

从需求描述中提取简洁的 kebab-case 名称：
- "添加用户登录功能" → `add-user-login`
- "修复移动端首页布局" → `fix-mobile-homepage`

### 3. 使用 fenix 原生 SPEC 生成器创建 SPEC

fenix 内置原生 SPEC 生成器（`bin/fenix_spec.py`），无需额外安装任何工具或外部 skill。
按以下流程创建完整的 change（proposal、design、specs、tasks）：

**3.1 创建 change 脚手架**

```bash
python3 .fenix/bin/fenix_spec.py new <name>
```

输出 JSON `{ok, path, error}`。若 `ok` 为 false（如名称非法或同名 change 已存在），
根据 `error` 调整名称或与用户确认后重试，不要强行覆盖已有 change。

**3.2 按依赖顺序生成 artifact**

```bash
python3 .fenix/bin/fenix_spec.py status --change <name>
```

`status` 输出每个 artifact 的状态：`done`（已生成）/ `ready`（依赖就绪，可生成）/
`blocked`（依赖未完成，附 `missingDeps`）。按依赖顺序逐个处理：

1. 对每个 `ready` 的 artifact，获取其生成指引：
   ```bash
   python3 .fenix/bin/fenix_spec.py instructions <artifact-id> --change <name>
   ```
   `instructions` 返回 `outputPath`、`instruction`、`template`（可直接作为文件骨架）
   与 `dependencies`。据此编写对应文件：
   - `proposal.md` → 明确 Why / What Changes / Capabilities / Impact
   - `specs/<capability>/spec.md` → 每个新能力一个 spec 文件，含 ADDED Requirements 与 Scenario
   - `design.md` → Context / Goals / Decisions / Risks
   - `tasks.md` → `##` 分组 + `- [ ] x.y` 勾选任务
2. 每完成一个 artifact 后重跑 `status`，继续处理下一个 `ready` artifact。
3. 重复直到所有 artifact 为 `done`（`isComplete` 为 true，`applyRequires` 的 `tasks` 就绪）。

### 4. 注册到 STATE.md

SPEC 创建完成后，运行：

```bash
python3 -c "
import sys; sys.path.insert(0, '.fenix')
from pathlib import Path
from core.state_machine import StateMachine
sm = StateMachine(Path('STATE.md'), None)
sm.add_spec('<spec-name>', {'status': 'drafted', 'priority': 5})
print(f'SPEC <spec-name> registered')
"
```

告知用户：**「SPEC `<name>` 已创建并注册。fenixd 会自动拾取并开始实现。」**

### 5. 自动提交 spec（防 merge-back autostash 熔断）

**必须在告知用户前完成提交。** 未提交的新 spec 目录会在 agent 派发时被 autostash 吞掉、且首个 merge-back 必熔断（已复现 2 次）。流程：

```bash
git add openspec/changes/<spec-name>/
git commit -m "[fenix] spec: <spec-name>"
```

- 只 add 该 spec 目录，**禁止 `git add .` / `-A`**（避免带入无关改动）
- STATE.md 已被 `.gitignore` 忽略，属运行时文件，**无需提交**
- 提交前检查脚手架产物完整：`.openspec.yaml` 缺失时补写（内容为 `schema: spec-driven` + `created: <年-月-日>` 两行，与其它 change 一致）
- 提交失败（pre-commit hook 报错等）时修复后重新提交，不要跳过 hook
- `--modify <name>` 更新完 artifacts 后同样执行本节提交

## SPEC 修改

如果用户传入 `--modify <name>`：读取现有 SPEC → 理解变更 → 更新 artifacts → 重置状态为 drafted。

## 规则

- 先澄清再生成，不猜测用户需求
- SPEC 要足够精确，让实现Agent 无需再提问
- 每个 Requirement 至少有一个可测试的 Scenario
- **确定能力全集时必须搜索归档目录**：`openspec/specs/` 仅存放当前活跃的 specs，历史的 specs 已归档到 `openspec/changes/archive/` 中。判断某个能力是新增还是修改时，必须同时搜索 `openspec/changes/archive/` 下的所有 `specs/` 子目录，确保不会将已存在的归档能力误判为新能力。
