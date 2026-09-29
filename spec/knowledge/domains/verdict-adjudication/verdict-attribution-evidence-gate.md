<!-- knowledge: capability=verdict-attribution-evidence-gate rev=1 sources=spec/archive/2026-09-15-add-verdict-credibility-gate -->

# 裁决归因证据门

judge 归因与证据绑定的确定性分级门：归因级别由证据构成机械决定，推测级归因不得作为打回 implementer 的依据。

## 现行规则

- judge 产出的每个非 PASS 场景归因必须携带确定性级别，级别由证据构成机械决定，与 judge 模型是否具备多模态能力无关：
  - `evidence-backed`：归因引用了场景的结构化证据（失败断言文本、算法标签、结构化字段如 first_frame_ok/blank_screenshot）且与证据不矛盾；
  - `speculative`：归因仅为推理链推测（无截图、无算法标签、无结构化字段支撑）；
  - `pending-visual`：归因涉及视觉现象（渲染/样式/布局类断言）但既无截图佐证也无算法标签。
- 无截图且无算法标签、归因未引用任何结构化字段时，该归因标为 `speculative`（附推理原文），不得以确定性口径进入打回上下文。
- 打回抑制：bug-found 打回的唯一归因依据全部为 `speculative` 级时，不触发打回 implementer（bug-found 转换被抑制）；该轮按环境存疑处理——重验一次或在 error 中写「归因证据不足待人工复核」。宁可重验/升级人工，不得带推测信号打回。
- 白屏标签约束归因方向：失败场景 evidence 含 `blank_screenshot: true` 时，归因必须引用该标签且结论限定为客户端渲染失败类（env 方向），不得归因于数据层（如 registry/项目列表）或产品逻辑。
- `pending-visual` 归因不阻塞但显式标注，允许随裁决输出；分级字段持久化进 report.json，人工可在 report 中一眼区分三类级别。
- 分级对纯文本 judge 与多模态 judge 同构：多模态 judge 的额外读图结论只能提升级别至 `evidence-backed`（须引用截图内容），不能绕过无证据降级。

## 溯源

- [2026-09-15 add-verdict-credibility-gate](spec/archive/2026-09-15-add-verdict-credibility-gate/) — 确立归因三级分级（evidence-backed/speculative/pending-visual）、推测级打回抑制与环境存疑处置、白屏标签约束归因方向与模型能力无关分级
