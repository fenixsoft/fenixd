# fix-visual-baseline-settle — 设计文档

## Context

取证定案（调查轮 2026-09-11，样本 `add-spec-status-modal-budget` 终验 report.json + 基线/截图逐像素分析）：

- 六轮 judge flaky 1/8/7/6/8/19，全部「DOM 断言全过 + 仅 SSIM 失败」。
- **16 个 modal/confirm 场景**（SSIM 0.68-0.79 恒 `diff_detected`，差异像素 90%+，基线中线亮度 248 vs 当前 127）：首轮固化基线时 antd Modal ~300ms fade 动画未完成，基线画面是「弹窗未出现」的污染态；`warning_streaks.json` 中最高 5 连证实恒比恒低、非随机。
- **3 个 menu 场景**（SSIM 0.89-0.93 `warning` 档，差异像素 2.71%）：渲染动画未 settle 的真实时序噪声。
- 根因缺口：`visual_diff.py:61` `compare()` 截图前无 settle、失败无重拍；`:91-100` 首轮基线无条件固化（健全性判定只挡 blank/low_contrast）；`browser.py:711` `_wait_stable` 只查 CLS 布局偏移+首帧文本，对 opacity 渐变完全不敏感。
- 现有 flaky 分类（verdict_check）、triage 门、守卫、暂停语义 SPEC 均不涉截图稳健性，零重叠。

## Goals / Non-Goals

**Goals:**

1. 截图前动画静置（settle），覆盖 CLS 检测不到的 opacity/transform 动画。
2. SSIM 低分限次重拍取最高分，压掉时序噪声型（A 类）。
3. 基线固化门 + `baseline_deferred` 顺延，阻断污染基线型（B 类）的新增。
4. 存量污染基线 suspicious 侦测 + 人工告警，处置权留给人。

**Non-Goals:**

- **不做按场景类型分类校准 SSIM 阈值**——取证显示阈值非瓶颈：0.68-0.79 调阈值要么无效要么放走真回归；0.89-0.93 靠 settle+重拍可拉回 0.95+。
- 不自动重建/覆盖已固化基线（自动重建有掩盖真回归风险，走人工确认）。
- 不改 `determine_scenario_status` 的阈值分档常量（SSIM_PASS/SSIM_WARN 保持 0.95/0.85）。
- 不动 judge 侧 flaky 分类逻辑本身（输入干净后 judge 归因自然简化）。

## Decisions

### D1：settle 落在 `VisualDiffer.compare()` 内部，而非步骤层或场景层外挂

**选择**：`visual_diff.py` 的 `compare()` 在 `page.screenshot` 前执行动画静置等待。

**理由**：`compare()` 是所有视觉对比的唯一入口（web_runner 单调用点，`web_runner.py:281`），在此处落点保证全量场景统一覆盖，无需场景文件改动。步骤层的 `_wait_stable` 是布局偏移导向，语义不同，不合并——合并会把动画静置强加给所有步骤（时延放大、且 09-06 的教训：`_wait_stable` 时长敏感，改共享路径有族谱级回归风险）。

**替代方案被拒**：按场景类型（modal/menu）在场景文件注入 settle 步骤——需要改全部存量场景文件 + planner 生成端，维护面大且靠自觉。

**实现形态**：页面注入 JS 轮询 `document.getAnimations()`，全部 `finished` 或达上限即返回；上限读配置 `verify_engine.visual_settle_timeout_ms`（默认 3000），0 = 禁用（行为与现状一致，逃生门）。

### D2：重拍取最高分、限 2 次、仍低维持原判定

**选择**：`pass=False` 时重拍（重拍前再 settle），限 `verify_engine.visual_retake_max`（默认 2）次，取最高 SSIM；结果记录 `retake_count` 与 `settle_waited_ms`。

**理由**：时序噪声单侧分布（重拍只会更干净），取最高分等价于「择优取证」；仍低则说明是真实差异，维持判定不掩盖回归。首拍即通过零附加开销（正常场景不受影响）。

**替代方案被拒**：取平均/取末次——平均会稀释真实差异，末次无择优语义。

### D3：固化门条件 = 该场景 step+assertion 全过，由 web_runner 传入

**选择**：`web_runner._execute_scenario` 在调用 `differ.compare()` 时传入场景通过性上下文（steps_failed 标志 + 断言失败列表）；`compare()` 内部在「基线不存在」分支先查此上下文，不满足则返回 `status=baseline_deferred`。

**理由**：固化决策需要的信息（步骤/断言结果）只在 web_runner 手里；visual_diff 保持纯函数式输入，不反向读 runner 状态。既有健全性判定（blank/low_contrast 拒固化，visual_diff.py:68-88）与新门串联：健全性判定在前（拒绝污染画面），通过性门在后（拒绝失败场景固化），两道独立防线。

**注意**：断言中含 `visual_ssim` 自身之外的视觉类断言不会出现（视觉结果不进 assertion_results），无循环依赖。

### D4：`baseline_deferred` 沿用 flaky/env 的「非打回」通道

**选择**：`determine_scenario_status` 对 `baseline_deferred` 不计为视觉失败（场景 status 不因此降档）；verdict_check 侧将其归入非驱动场景（`:593-614` 同 flaky/env 处理，豁免清单 `_EXEMPT_ALLOWED_CLASSES` 通道不动，另在视觉 status 白名单中放行）。

**理由**：`baseline_deferred` 是「本轮无法对比」，与 flaky/env 同属「不构成打回依据」语义；复用既有通道避免新增分类枚举。前端报告渲染按未知 status 容忍处理（已有先例：`baseline_rejected`、`baseline_created` 均非三档枚举值）。

### D5：污染基线侦测复用 warning_streaks 同目录持久化模式，suspicious 只标记不处置

**选择**：`.fenix/verify-progress/<spec>/baseline_streaks.json` 记录每场景连续 diff_detected 计数；达 3 发 admin 告警并写 `baselines/<name>.suspicious` 标记文件；`baseline_deferred` 不累计不清零；任一轮 SSIM 恢复非 diff_detected 清零并撤 suspicious 标记。

**理由**：与 `warning_streaks.json` 同构（已验证的持久化模式，跨 daemon 重启存活）；suspicious 只标记+告警，重建交人工确认——自动重建在「基线对、当前版本真回归」的镜像场景下会洗白回归，风险不可接受。

**告警渠道**：复用既有 admin 告警通道（`.fenix` 下人工告警 jsonl），正文含场景 ID、各轮 SSIM 值、基线文件路径，与人工冻结/失效可修等既有告警同模式。

### D6：配置键收敛在 `verify_engine` 段，向后兼容缺省

| 配置键 | 默认 | 语义 |
|---|---|---|
| `verify_engine.visual_settle_timeout_ms` | 3000 | settle 等待上限；0=禁用 |
| `verify_engine.visual_retake_max` | 2 | SSIM 低分重拍次数上限 |

既有 spec 无这两键（零迁移）；读侧缺省取默认值。**提醒**：新增配置项须带 Dashboard 界面（`fenix-new-config-needs-dashboard-ui` 约定）——若两键纳入设置页需在 tasks 中同步 UI 项；最小实现可仅走 YAML（verify.yaml 契约段已有 per-spec 覆盖通道），tasks 中按最小化处理为 YAML-only + 文档标注。

## Risks / Trade-offs

- **[settle 增加每场景时延]** 首拍通过的干净场景增加一次动画检查（页面注入 JS，通常 <50ms）。→ 上限 3s 且仅在 `getAnimations()` 非空时等待；正常页面动画瞬时 finished，实测影响毫秒级。
- **[重拍放大写盘]** `diff_detected` 场景最多 3 次截图落盘（current 覆盖写，不新增文件）。→ 覆盖式命名不变，磁盘无增量；每次重拍间 settle 有天然节流。
- **[固化门放慢基线建立]** 首轮有失败场景的基线顺延到下轮。→ 语义即「宁缺毋污染」；顺延不丢（`baseline_deferred` 显式留痕，下轮干净时正常固化）。
- **[suspicious 误报]** 反复动画抖动的场景可能三连 diff_detected 但基线无辜。→ 告警只是提醒人工核实，不自动处置；settle+重拍落地后此类抖动大幅减少，误报面收窄。
- **[页面 JS 注入兼容性]** `document.getAnimations()` 需较新 Chromium；headless chromium 满足。→ 注入失败（老内核/异常页面）按 settle 超时退化处理，不放大失败（与 CLS 检测同容错模式）。
- **[judge 输入变化]** 修复后 flaky warning 大幅减少，judge 既有「跨轮已裁决写回」路径流量下降。→ 纯流量变化无接口变更；verdict_cache 不受影响。

## Migration Plan

1. 实现四件套（settle / 重拍 / 固化门 / suspicious 侦测）+ `baseline_deferred` 下游兼容，TDD 全绿后合并。
2. 合并后重启 daemon（merge-back 后旧码陷阱）；存量污染基线不清理——下一轮起固化门阻断新增污染，settle+重拍压制噪声，suspicious 告警自然指出存量 16 条污染基线，人工确认后删除基线文件即可在下轮重建干净基线。
3. 回滚：改动集中在 `visual_diff.py`/`web_runner.py`/`browser.py`（无 schema/配置迁移），git revert 即回滚；两个新配置键缺省行为 = 现状（settle 默认开但干净页面零等待，重拍仅在失败时发生），无回滚残留。

## Open Questions

（无——四件套边界与不做清单均已在调查阶段定案。）
