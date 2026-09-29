<!-- knowledge: capability=attribution-freshness-governance rev=1 sources=spec/archive/2026-09-15-add-verdict-credibility-gate -->

# 归因新鲜度治理

归因固化治理三件套：跨轮缓存归因打标、批量硬编码归因拒绝落盘、视觉基线防污染——假归因不得跨轮固化。

## 现行规则

- 跨轮缓存归因打新鲜度标：verdict_cache（跨轮指纹缓存）命中的场景归因写入 report / 打回上下文时，必须携带「跨轮缓存复用」标记（`cached_from_previous_round: true` 与来源轮次信息），禁止以本轮新证据的口径原样呈现；打回上下文的消费者（implementer prompt、report 渲染）可见该标记。
- 缓存归因不得作为本轮唯一打回依据：本轮打回依据全部来自缓存归因（无本轮新增 evidence-backed 证据）时，按 verdict-attribution-evidence-gate 的推测级同规则处理（抑制打回，转重验或人工复核）。
- 禁止批量硬编码归因落盘：报告合成/丰富路径（含 judge 自建脚本）不得将同一硬编码归因文案批量套用到多个场景；单轮落盘的多个场景归因文本归一化空白后逐字相同且场景数 ≥ 3 时，合成器拒绝落盘并记 error 日志（列出涉及场景），要求逐场景归因。该校验内置在框架的 report 合成/丰富入口（不依赖人工审查发现 judge 自建脚本）。
- 视觉基线防污染：视觉基线建立（首跑固化）时做健全性判定，环境性伪画面不得固化为基线；截图命中 blank_screenshot / low_contrast 标签时拒绝固化该基线，场景视觉断言按环境存疑处理（记 warning，不产生像素比对结论），后续轮次该场景重新尝试建立基线（干净截图成功后正常固化）。
- 基线建立失败可观测：基线因防污染被拒绝固化时，report 中该场景记录「baseline_rejected + 原因标签」，供人工与后续轮次追溯。

## 溯源

- [2026-09-15 add-verdict-credibility-gate](spec/archive/2026-09-15-add-verdict-credibility-gate/) — 确立跨轮缓存归因强制打标与缓存归因打回抑制、批量同文案归因（≥3 场景同文）拒绝落盘、视觉基线健全性防污染三件套
