# Proposal: add-deliverable-declaration-triage

## Why

2026-09-06 add-verify-multi-kind-runner 事故：tasks.md Deliverables 声明路径笔误
（`core/verification.py`，实际落点 `core/pm_engine/verification.py`）只能等实现 run
收工时撞守卫才发现，叠加守卫 dispute 分支 AttributeError，3 轮完整实现被反复打回
重做，累计烧掉 94.12 USD / 1.45 亿 input tokens；且第 4 轮重派仍在进行。

机械规则（晋升 lint 的存在性校验 + basename 模糊匹配）可以拦截大部分笔误，但存在
原理性盲区：

1. 仓库有多个同名 basename 文件 →「唯一命中」阈值失效，拦不住；
2. 笔误出现在 basename 本身（如 `verifcation.py`）→ 模糊搜索完全 miss，拦不住;
3. 语境等价（design 写「core/verification.py（serve 需求反推）」实指 pm_engine 包
   内既有文件）→ 任何字面规则都无法裁决。

这三类是**语义问题**，最终裁决必须由 LLM 完成。本 SPEC 建立三层纵深拦截，把「声明
路径 vs 仓库现实」的矛盾在零成本位置（晋升前、派发前）暴露，剩余漏网在收工守卫
打回前由 LLM 语义终审裁决，杜绝「一个声明笔误烧一整轮实现」的事故形态。

## What Changes

1. **晋升 lint 扩展（drafted → ready，零成本拦截）**：`lint_declared` 新增两条规则
   —— `kind: modify`/`reference` 路径在主树必须存在（确定性，零误拦）；`kind: new`
   路径不存在时做 basename 模糊匹配，仓库内**唯一**命中即判疑似笔误拒绝晋升，报错
   信息直接给出疑似目标。fail-open 惯例保留（lint 自身故障不阻塞流水线）。

2. **派发前干跑处方注入（实现者开工前知悉矛盾）**：dispatch implementer 构建提示词
   时干跑 `extract_declared` + 主树存在性检查 + basename 匹配，把声明清单的仓库
   现实快照（含疑似笔误候选）注入实现者提示词，并约定：判断系笔误时以实际路径实现
   并登记 deliverable-dispute，不得静默改变交付落点。

3. **守卫缺件 LLM 终审（打回前的语义裁决）**：收工守卫判缺件后、打回动作前，派
   轻量单轮 judge run（复用既有 `planner-judge-` 范式，run 前缀 `dispute-judge-`），
   输入 = 缺件清单 + spec 语境摘录 + 实现者 findings + 模糊匹配候选，输出固定契约
   裁决 JSON。daemon 按裁决**机械执行**：
   - `typo`（笔误/语义等价）→ daemon 修正 tasks.md 声明段 path → 审计留痕 → 重跑守卫对账；
   - `reference`（应归运行时写入目标/既有引用）→ 声明软化为 reference → 审计留痕；
   - `missing`（真缺件）→ 走既有打回/重派路径；
   - `unclear`/低置信 → 走既有 dispute 转人工通道（blocked 待人工裁决，原样保留）。

4. **审计留痕与防洗白**：judge 裁决 JSON + daemon 修正 diff 全部落 dispute 审计流，
   人工可复核、可回滚（回滚 = 人工恢复声明段 + 既有流程重派）。judge 自动裁决不得
   静默放行任何缺件——每条缺件必有裁决记录或人工裁决记录。

## Capabilities

### 1. deliverable-declaration-triage（交付物声明三层对账）

- 晋升 lint：`modify`/`reference` 存在性硬校验 + `new` 路径唯一 basename 命中疑似笔误拦截；
- 派发处方：声明清单仓库现实快照注入实现者提示词；
- 缺件终审：LLM judge 裁决 + daemon 机械修正 + 审计留痕 + 人工兜底。

## Impact

- **代码**：`core/deliverables.py`（lint 规则扩展 + 模糊匹配工具）、
  `core/pm_engine/verification.py`（守卫缺件分支接入 judge）、
  `core/pm_engine/dispatch.py`（judge 结果消费 + 裁决执行 + 审计落盘）、
  `core/pm_engine/prompt_builder.py` 或 dispatch 提示词构建段（处方注入）、
  `tests/`（新增回归）。
- **配置**：judge 复用既有 agent run 派发与模型路由机制，**不新增配置键**
  （若实现中发现必须新增，须同步 Dashboard 设置页能力——见全局约定）。
- **行为兼容**：无声明段存量 spec 行为不变（lint 跳过 + 守卫回退提取）；judge
  仅在守卫判缺件时触发，正常通过路径零开销。
- **不做什么**：不为晋升 lint 拒绝场景引入 judge（drafted 卡住零烧钱成本，报错
  附模糊匹配候选已够）；不动 fast-track 与 full 的状态机流转。
