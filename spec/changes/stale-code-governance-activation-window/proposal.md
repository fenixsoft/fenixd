# 治理代码合并后至自愈重启之间的旧代码处置窗口收敛

## Why

本次实证：治理代码 21:17:28 merge 主树后，stale_code_selfheal 等待「连续空闲 300s」直到 21:57:41 才触发生效重启，40 分钟窗口内 daemon 以旧代码处置了两个新升级事件——frozen 预检、空壳豁免、看护归档回落、终态归因四个已修能力全部不生效，产生两条假告警并误烧链配额（admin_attempts=1×2）。值得立项的方向：merge 回主树即以高优先级请求重启（不等空闲窗），或 stale 检测在场期间对升级边信号的链派发延迟至重启后消费，或缩短自愈空闲阈值。检查器可将「merge 落主树但 daemon baseline 落后」作为显式可观测状态暴露（当前仅 WARNING 日志）。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=fix-scenario-revision-choice-registration-surface::spec-review-rejected，source=startup）
- 立项时间：2026-11-03T14:09:15.205986+00:00
