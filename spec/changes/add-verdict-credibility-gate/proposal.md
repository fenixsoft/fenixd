# 提案：add-verdict-credibility-gate（验证裁决可信度门）

## Why

add-spec-status-modal-budget 事故（2026-09-09/10，烧 $163+）暴露裁决信号链的四层缺陷：

1. **judge 无截图闭眼归因**：白屏场景 screenshots 为空，judge 凭「行选择器无匹配 → 项目列表空 → registry ignored」推理链给出确定性归因，写进打回上下文——implementer 收假信号修无可修（真缺陷是 5 并发白屏，与 registry 无关）。
2. **假归因跨轮固化**：judge 自造的 enrich_report.py 把硬编码常量 `CROSS_FIRST_FAILED` 一次套 12 个场景；verdict_cache 指纹命中后旧归因原样复用；白屏被固化为视觉基线（4714B 纯白图），后续轮次 SSIM 对白屏基线反而 pass。
3. **admin 全程失明**：inconclusive（全批 blocked-env）暂停不产生 error 终态产物 → repeated_failures 天然不计数；stuck 检测被每小时重验的「无效进度」骗过；blocked_stuck 只查 blocked 态——三层检测口径完美错过，admin 从未被唤起，循环烧掉 9 轮验证（$24）无人知晓。

用户已拍板：B2 证据门不得依赖 judge 多模态能力（白屏检测算法化，模型读标签不读图）；B7 阈值定为连续 4 轮 blocked-env 呼叫 admin。

## What Changes

- **verify_engine 截图落盘时算法判定截图健全性**（纯色/低对比度/尺寸异常），产出结构化标签（`blank_screenshot` 等）写入场景 evidence——纯算法，不依赖任何模型能力。
- **judge 归因确定性分级门**：归因必须绑定证据——无截图的归因只能标「推测」，不得作为打回 implementer 的依据；涉及视觉现象但无算法标签佐证的归因降级为「待定」。分级规则能力无关（文本 judge 与多模态 judge 同一规则，多模态只扩大裁量范围不降低下限）。
- **归因固化治理**：verdict_cache 指纹命中的历史归因打「跨轮缓存复用」标，禁止原样作为新证据写打回上下文；报告合成禁止批量套用同一硬编码归因常量（enrich_report.py 模式）；视觉基线建立时拒绝纯色/低对比度截图（白屏不得固化为基线）。
- **inconclusive 循环升级**：`_inconclusive_attempts` 达到 4（可配 `verify_engine.inconclusive_escalate_attempts`）时，向 admin store 写 kind=SIGNAL 记录，经 admin_monitor 摄取唤起 Administrator，附环境核查处置建议；与 B6（recovery 尊重暂停标记）配合成闭环。

## Capabilities

### New Capabilities
- `screenshot-evidence-labeling`: 截图健全性算法标签——verify_engine 截图落盘时以像素方差/直方图/低对比度指标判定白屏、纯色、低对比度，写结构化标签进场景 evidence 与 report。
- `verdict-attribution-evidence-gate`: 裁决归因证据分级门——judge 归因与证据绑定分级（证据充分/推测/待定），推测级归因不得进入打回上下文作为修复依据。
- `attribution-freshness-governance`: 归因新鲜度治理——跨轮缓存归因打标、禁批量硬编码归因落盘、视觉基线防污染三件套。
- `inconclusive-loop-escalation`: inconclusive 循环升级——连续 blocked-env 达阈值（默认 4）向 admin store 写 SIGNAL 唤起 Administrator。

### Modified Capabilities
<!-- 无 requirement 级修改：归档能力 verdict-evidence-taxonomy（证据分类学）与
     verify-environment-sanity-gate（环境健全性门）的既有 requirement 不变，
     本 SPEC 为其下游新增能力。 -->

## Impact

- **代码**：`core/verify_engine/`（截图标签、基线防污染）、`core/pm_engine/verification.py`（升级写入）、`core/admin_monitor.py`（SIGNAL 摄取与处置建议）、judge 提示词/prompt_builder（归因分级规则）。
- **影响的行为**：judge 打回上下文的内容构成；视觉基线建立路径；inconclusive 暂停分支的副作用。
- **不受影响**：env_gate 既有降级语义（B1 已落地的 blocked-env 判定）、recovery 暂停拦截（B6 已落地）、验证场景执行链路。
- **风险**：归因分级可能让部分真实打回变保守（推测级不能打回）——设计上以「升级人工/重验」代替「带推测打回」，宁可多一次重验不可带假信号打回（本次事故的直接教训）。
