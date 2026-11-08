## Context

cloud-phone 首跑告警中 6 条（3 major 白名单 + 3 info 散件）源于框架自身初始化产物：

- `templates/gitignore-fenix.txt` 用 `!.fenix/verify.yaml` 放行白名单文件，但 `fenix-init` 写入后从不 `git add`——「入库意图已声明、文件却未入库」，首轮周期盘点（`maintree-stray-wip-sweep`）即报 whitelist_untracked major，且该信号按设计只唤起人工二选一处置。
- 播种产物 `.claude/agents/`（`implementer.md`/`verifier.md`）不在 gitignore 覆盖范围（模板只盖 `.claude/worktrees/`），成为 untracked 散件触发首现提示。
- `.fenix/config.template.yaml` 的 llm/agents.models 注释写「未配置时所有 Agent 使用默认环境变量模型（现状行为）」——claude 形态实际是环境继承 CLI 默认档，dsh 形态是对称回落 dsh profile 默认档（SPEC ① 兑现后），「环境变量模型」对两形态都不准确。
- `skills/fenix-setup/SKILL.md` 现有流程无模型配置检查环节（`mkdir` 步骤含 `.claude/agents` 但配置引导缺失），新手首跑撞上模型链/CLI 类告警时无处可查。

## Goals

- 框架不再对自己的初始化产物发告警（消除产生源而非压制告警）
- 模板注释与实际回落语义（含 SPEC ① 落地后）一致
- 新手经 setup 引导即完成模型配置核对面，首跑告警有处可查

## Non-Goals

- 不自动 commit（git add 到 staged 为止，提交时机永远留给用户）
- 不改变白名单机制语义（放行规则与巡检判定不动，只补「入库」这最后一环）
- 不新增配置键、不改 Dashboard

## Decisions

### D1 git add 用离散路径而非 `git add .`

只 add 两个白名单文件（`.fenix/todo.md`、`.fenix/verify.yaml`），MUST NOT `git add .`——骨架生成时项目里可能已有用户未跟踪文件（如 `scripts/nat_check.py`），批量 add 会替用户做出入库决定。unborn 分支（零提交史）`git add` 正常工作，无需特殊处理。

### D2 gitignore 追加判据与幂等

`.claude/agents/` 规则追加复用 `append_gitignore` 既有幂等判据模式（取关键规则行 `^\.claude/agents/$` 判存在），规则带成因注释（框架播种运行时产物）。模板侧（新项目）与 `--ensure-gitignore` 侧（既有项目）同一段实现产出，禁止两处文本漂移。

### D3 模板注释改写范围：只动误导表述

llm 段「未配置时所有 Agent 使用默认环境变量模型（现状行为）」改为按 harness 分形态的两句话描述；agents.models 段「按 Agent 角色分配模型（可选）。未列出的角色使用默认模型。」补一句无分配默认行为分形态说明。其余配置注释不动（控制模板 diff 面积）。

### D4 setup 引导以「检查 + 指引」形态写进 SKILL.md，不做自动探测脚本

SKILL.md 增加的模型配置检查是**指引执行者（Agent/人）做读取与核对**的步骤说明（读 config.yaml → 核对 providers/models 形态 → 分支指引），不引入新脚本依赖——与既有 SKILL 的文字流程风格一致。首跑告警解读覆盖三类（白名单脱落→初始化已自举不会再有/存量怎么处置；散件首现→预防性 ignore 已内置；契约模板态→实现期 info 属预期，进入验证期前完成裁决）。

## Risks

- 既有项目 `.claude/agents/` 若已被用户手工跟踪（入库意图），追加 ignore 规则不影响已跟踪文件（gitignore 只作用于 untracked）——无破坏面
- 模板注释改动使 fenixd 自身 `.fenix/config.yaml` 与模板注释措辞短暂不一致——config.yaml 是运行时文件不随模板分发，无同步义务

## Migration Plan

- 新项目：init 即自举，零迁移
- 既有项目：下次 `--ensure-gitignore`（或 fenix-setup 重跑）幂等补齐 ignore 规则；存量白名单未入库文件由人工 `git add`（登记 `.fenix/todo.md`）

## Revert Plan

四个文件均为独立增量改动，revert 各自回退无交叉依赖；已 staged/已追加规则保留无害。
