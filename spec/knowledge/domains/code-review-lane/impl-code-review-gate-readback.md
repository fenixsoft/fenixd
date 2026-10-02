# 审查报告读侧判读归属

<!-- knowledge: capability=impl-code-review-gate-readback rev=2
     sources=spec/archive/2026-09-25-fix-impl-code-review-gate-readback,spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

收尾审查报告的读侧判读：判读发生在哪道门、用什么判据。

## 规则

- 实现 run 的成功收口不做收尾审查报告校验：实现产物硬门无审查报告校验项，报告校验不挂在 run 结束点。
- 报告判读统一在 `testing → verified` 的 join 门执行，判据为：产物存在、`status` 在白名单（`completed`/`unavailable`）、`(branch, merge_base, head_commit)` 指纹新鲜；指纹不匹配的产物按 stale 处理，不参与裁决（见 [impl-ocr-join-gate](impl-ocr-join-gate.md)）。

## 溯源

- 2026-09-25 fix-impl-code-review-gate-readback（spec/archive/2026-09-25-fix-impl-code-review-gate-readback） — 新建读侧容错：实现产物硬门的审查报告探测改「worktree 优先、主树回退」双候选，两处经同一套校验（status 白名单 / findings 与 dispositions 逐条对账 / rejected、deferred 须附非空 reason）；主树回退候选加 mtime 新鲜度守卫（resume 复用 worktree 跳过硬拦）；两处均缺失时才判失败且文案并列给出两个已探测位置；候选存在但未过校验时原样上抛该候选归因（陈旧候选归因含「陈旧」），不折叠为「报告缺失」。
- 2026-09-26 add-impl-ocr-parallel-lane（spec/archive/2026-09-26-add-impl-ocr-parallel-lane） — 同 run 产物硬门整体摘除（`_check_impl_code_review_artifact` 退出生产调用），上述读侧判读由 join 门判据（产物存在 + status 白名单 + 指纹新鲜）替代。
