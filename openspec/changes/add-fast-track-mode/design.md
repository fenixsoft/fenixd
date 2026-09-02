# Design: add-fast-track-mode

## Context

当前全流程由 PMEngine 事件驱动：`drafted → ready` 后派发 implementer run（独立上下文 + worktree 实现 + merge），成功后排队 verifier；验证流水线先派 planner run 设计场景（场景冻结），再由 verifier run 三阶段验证与判定，判定输出经 verdict_check 确定性校验。各 agent 之间靠 spec 文件、scenarios.json、verify report 传递信息，各自重复探索代码库。

对简单需求，这段链路的冷启动探索开销重复支付 3 次（implementer / planner / verifier），且多 run 串行等待。历史教训（mock 验证假阴性放大器、零变更哨、交付物守卫的由来）表明压缩流程时护栏不可省略。

用户已确认的四项决策：
1. **执行形态**：状态机不变，单 run 全包（实现+场景设计+验证+判定），护栏保留，run 内守卫替代 run 间守卫。
2. **模式建议**：fenix-new 需求 Agent 对话中评估复杂度并明确建议，用户确认后写入 spec 元数据。
3. **bug 处理**：run 内修复受 fix 预算约束，超预算自动升级完整模式。
4. **自验自判风险**：框架侧硬校验兜底（verdict_check 确定性校验）。

## Goals / Non-Goals

**Goals:**
- 简单需求端到端由单个 agent run 完成，消除跨 agent 的信息重复与冷启动开销
- 快速路径与完整模式共用状态机、护栏体系与 merge 语义，不产生第二套生命周期
- 用户在 fenix-new 时获得明确模式建议并可覆盖
- 自验自判的判定偏差有框架侧确定性校验兜底

**Non-Goals:**
- 不改动状态转换图（VALID_TRANSITIONS 不变，无新增状态）
- 不为复杂需求改变完整模式流水线行为
- 不新增全局配置开关（mode 为 per-spec 元数据；避免配置项 + Dashboard 配置 UI 的额外负担，回滚手段为读侧忽略 mode 字段）
- 不做框架自动复杂度打分（决策 2 已确认为对话内评估）

## Decisions

### D1: 执行形态 — 单 run 全包 + 守卫保留（用户确认）

fast-track spec 进入 ready 后派发一个 `run_fast_track`，单上下文完成四段工作。备选：
- *旁路状态机轻量 lane*：拒绝——失去防伪成功护栏，有 mock 假阴性放大器前科。
- *两 run（实现+验证各一）*：拒绝——省不掉 planner 与状态衔接开销，收益不足。

### D2: mode 元数据存放 — spec 目录 `.openspec.yaml`，读侧缺省 full

mode 写入 `openspec/changes/<name>/.openspec.yaml`（与 `schema: spec-driven`、`created` 同级新增 `mode` 行）。理由：
- mode 语义属于 spec 定义（创建时确定、随目录提交、merge-back 安全），不应放运行时 STATE.md（gitignore、可被重置）
- 避免双写漂移：dispatch 派发前直接读 `.openspec.yaml`，字段缺失/非法一律按 `full`，存量 spec 零迁移

### D3: fast-track agent 模板 — `agents/fast-track.md`

新增提示词模板，四段职责（实现 → 场景设计 → 场景验证 → 判定）+ 统一结果文件 schema + 护栏告知（零变更哨、交付物清单、fix 预算）。`prompt_builder` 增加 fast-track 段；场景设计要求沿用现有场景 schema（兼容 scenario freeze 语义——单 run 内 planner 与 verifier 是同一上下文，冻结约束天然满足，但仍要求场景集落盘以便升级完整模式后 verifier 复用）。

### D4: 统一结果文件 — 扩展 `.fenix-run-result.json`

复用现有 run 结果文件机制，fast-track run 在其中增加验证段（设计场景、逐场景结果、最终判定、证据）。daemon 端 fast-track 分支读取后：走 verdict_check 硬校验 → 通过则推进 `implemented → testing → verified`；失败则按失败重派并累计计数。独立新文件的备选被拒绝——多一个文件协议就多一处漂移点。

### D5: 超预算升级的衔接点 — 保留分支、置 implemented、verifier 流水线接管

fix 预算耗尽时：`mode` 改写为 `full`（`.openspec.yaml` 同步更新）、实现成果以分支形式保留（等价于完整模式 implementer 成功后的状态）、spec 置 `implemented`、派发完整模式 verifier 流水线（planner + verifier 从头探索，此时 spec 已存在，信息传递成本可接受）。升级原因写入 spec entry `error` 字段供人工追溯。**绝不**把已有实现成果丢回 ready 重跑 implementer。

### D6: 判定独立性缓解 — 硬校验三要素

verdict_check 扩展对统一结果文件校验：① 报告结构完整（场景/结果/判定字段齐全）；② 场景全量执行（设计集与执行集一致，无静默遗漏；豁免走现有豁免合法性规则）；③ 逐场景证据存在性。agent 文本宣称不作为通过依据——与完整模式 verifier 的判定信任模型一致（框架只信可校验的输出）。

### D7: fenix-new skill 更新 — 项目源与安装副本同步

`skills/fenix-new/SKILL.md`（项目源）与 `~/.claude/skills/fenix-new/`（安装副本）同步更新：澄清阶段增加复杂度评估（影响面/模块数/是否含 UI 或迁移/预期场景数量）与明确建议话术；新增 `--fast-track` / `--full` 显式参数；确认后写入 `.openspec.yaml` 的 `mode` 行。评估在对话内完成，不引入代码级打分器（用户确认的决策 2）。

## Risks / Trade-offs

- [自验自判系统性偏差：同一 agent 可能对自家实现放水] → 硬校验三要素（D6）+ fix 预算 + 超预算升级完整模式（D5）三重兜底；升级路径保证最坏情况仍回到独立 verifier
- [用户被建议误导、复杂需求走了 fast-track] → 升级机制保证最终正确性（代价是浪费一次 fast-track run）；Dashboard 模式标记 + 升级原因记录提供事后可观察性
- [统一结果文件 schema 漂移] → schema 在 `agents/fast-track.md` 与硬校验器两处对齐，单测锁定；解析失败一律按失败处理（fail-closed），不静默通过
- [fast-track run 内验证环境复杂度（app 启动、端口冲突）] → 复用现有 worktree-test-server 机制，验证环境规则与完整模式 verifier 相同
- [run 内修复轮次不可控烧 token] → fix 预算沿用现有 fail 预算配置，单 run 内修复轮次显式计入预算，超限即升级不再续跑
- [存量 spec / 新旧路径行为差异] → mode 字段缺省 full，读侧容错；完整模式代码路径零改动，回滚仅需读侧忽略 mode

## Migration Plan

1. 合入后 daemon 读侧识别 `mode` 字段，存量 spec（无字段）全部按 full 处理，行为零变化
2. fenix-new skill 更新后新创建的 spec 才可能携带 `mode: fast-track`
3. 回滚策略：读侧忽略 mode 字段（或 revert 读侧 commit），所有 fast-track 元数据成为惰性数据；在途 fast-track spec 按升级路径规则转为 full 处理

## Open Questions

- fix 预算数值是否为 fast-track 单独配置（如 `agents.fast_track.fix_budget`）——实现期确认，初版沿用现有预算配置不加新键
