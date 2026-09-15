# 设计：add-verdict-credibility-gate

## Context

add-spec-status-modal-budget 事故链（2026-09-09/10）：5 并发白屏 → judge 无截图误归因「registry ignored」→ 硬编码常量+指纹缓存+白屏基线三层固化 → implementer 两轮修无可修 → inconclusive 循环 9 轮烧 $24 且 admin 全程失明。B1（白屏降级 blocked-env，b04843e）与 B6（recovery 尊重暂停标记，120a9ad）已落地，本 SPEC 治理剩余的裁决信号链缺口（B2 证据门、B3 固化治理、B7 升级通道）。

用户拍板的两个约束：
- B2 不得依赖 judge 多模态能力——白屏检测算法化，模型读标签不读图；
- B7 阈值 = 连续 4 轮 blocked-env。

## Goals

1. 截图健全性由算法判定并结构化落盘，judge 归因与证据机械绑定；
2. 假归因无法跨轮固化、无法批量套用、无法污染基线；
3. inconclusive 循环达到阈值时 Administrator 必然被唤起。

## Decisions

### D1 截图标签：判定逻辑独立成模块，browser.py 落盘时调用

新建 `core/verify_engine/screenshot_lab.py`（纯函数：`classify_screenshot(path) -> dict`，像素 std + 主色占比 + 低对比度指标），`browser.py` 的 `screenshot()` 落盘后调用并把标签并入返回值；引擎把标签写入场景 evidence。依赖 Pillow/numpy（skimage 已在用，其依赖链自带），异常时 warning + 跳过（不阻断截图主流程，spec Scenario 覆盖）。标签阈值集中为模块常量，便于调参。

### D2 归因分级由框架机械计算，不由 judge 自报

教训：enrich_report.py 证明 judge 自律不可依赖。分级规则：judge 只输出归因文本 + 引用的证据引用列表（断言文本/结构化字段/算法标签）；**框架侧校验器**在报告落盘前根据「场景 evidence 构成 + 归因引用」机械算级（evidence-backed / speculative / pending-visual），并执行门禁：
- 全部归因为 speculative → 抑制 bug-found 打回，转重验一次或写「归因证据不足待人工复核」；
- evidence 含 blank_screenshot 而归因未引用它或归因到数据层 → 判 env 方向并改写归因级别为 evidence-backed(env)。

校验器落点：report 落盘/打回上下文组装前的统一入口（verification.py 的报告处理链），与 enrich 类后处理同位但为框架内置代码。分级结果持久化进 report.json（`attribution_level` 字段）。

### D3 缓存归因打标：verdict_cache 命中路径补字段

verdict_cache 命中复用归因时（现有指纹匹配路径），为复用的 first_failed_step/evidence 附加 `cached_from_previous_round: true` 与来源轮次；打回上下文组装时透传。缓存归因与本轮证据的分级按 D2 规则合并计算——纯缓存归因视同 speculative 口径。

### D4 批量硬编码归因校验：落盘前归一化查重

报告落盘前对全部场景归因文本归一化（strip+空白折叠）查重：≥3 个场景逐字相同 → 拒绝落盘、记 error（列出场景名），要求逐场景归因后重合成。与 D2 校验器同一入口。

### D5 基线防污染：基线建立路径复用 D1 标签

视觉基线首跑固化处（baselines 写入点）先调 `classify_screenshot`：命中 blank_screenshot / low_contrast → 拒绝固化，场景记 `baseline_rejected` + 标签，视觉断言本轮按环境存疑（warning）；后续轮次截图干净时正常建立。

### D6 B7 升级：复用 STORED_SIGNAL 通道

`verification.py` 的 `_handle_env_blocked_inconclusive`（与 judge 自述环境暂停分支）在 `_inconclusive_attempts` 达到 `verify_engine.inconclusive_escalate_attempts`（默认 4）时，向 admin store 写 kind=SIGNAL 记录（type=`inconclusive_loop`，附 spec 名、连续轮数、末轮 blocked_env 数、探针摘要）；`admin_monitor._detect_family_explosion` 的 STORED_SIGNAL_TYPES 集合加入 `inconclusive_loop`，SUGGESTIONS 增加环境核查清单与恢复路径（解冻+清计数）。计数不清零则 recovery（B6）保持跳过，人工处置是唯一出路——与「暂停自动重验」语义闭环。

## Risks

- **归因分级过严拖慢正常循环**：真实缺陷若证据引用不规范会被降级 speculative → 多一次重验。缓解：evidence-backed 的引用门槛定义为「引用失败断言文本」这种最低成本动作（judge 本就输出该文本）；门禁只抑制「纯推测打回」，不抑制有断言文本支撑的打回。
- **批量查重误伤**（多个场景确实同因同文案）：门槛设 ≥3 且要求逐字相同；误伤时 error 日志列出场景，重合成即可，不烧预算。
- **基线拒绝固化导致视觉断言长期 warning**：白屏基线本就无断言价值；干净截图建立后自愈，spec Scenario 覆盖。
- **SIGNAL 噪音**：阈值 4（3 次重验+1 次暂停）内不触发，且 escalation_cooldown 节流沿用既有机制。
