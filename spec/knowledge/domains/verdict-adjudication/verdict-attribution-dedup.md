# 批量归因查重级联豁免

<!-- knowledge: capability=verdict-attribution-dedup rev=1
     sources=spec/archive/2026-10-09-evo-add-attribution-dedup-cascade-exemption -->

批量归因查重门的同因组豁免：依赖失败传播（dependency_skipped）场景的归因本就逐字相同，单列同因组免于「≥3 同文即拒」判据，不再为合法级联误付重合成；模板套用防线的判拒语义保持不变。

## 规则

- 依赖级联同因组单列：批量归因查重把 dependency_skipped（依赖失败传播）场景单列为同因组，组内不参与「归一化后逐字相同且组内 ≥3 即拒」判据，仅校验非样板字段。一组同文归因场景全部为 dependency_skipped（如宿主缺工具导致的依赖级联 blocked-env）时不判拒绝、不触发重合成，验证照常收口。
- 豁免锚点只认框架结构化合并的标记：dependency_skipped / skipped_depends_on 由引擎写入执行结果条目，查重门统一入口（首轮/重试/重合成三处轮次共用）按 scenario_id 把引擎执行结果条目的标记合并进裁决报告场景条目；豁免判据只认这层框架合并的标记。judge 自行申报的同名字段不作为豁免依据——报告条目自带 dependency_skipped 标记而引擎执行结果无对应依赖跳过记录时，不豁免，按普通同文组判据处理（防实现 run 伪标逃逸，防御在数据流层闭合）。
- 混合组判拒语义不变：同文组含真实 failed 场景（非依赖跳过）时仅对非级联子集计阈值，满足 ≥3 照常判拒（模板套用嫌疑），reason 文案不变；既有归一化细分（失败步骤序号/断言 label 逐场景不同不计入命中）的防套用能力不回退。
- 豁免决策留痕：豁免命中时查重结果结构携带豁免段（组清单与原因）返回，验证日志记录豁免原因与场景清单；豁免不写违规记录、不触发拒绝收口链，可事后审计豁免是否被滥用。查重阈值 ≥3 与归一化指纹构成不在本能力调整范围。

## 溯源

- 2026-10-09 evo-add-attribution-dedup-cascade-exemption（spec/archive/2026-10-09-evo-add-attribution-dedup-cascade-exemption） — 新增依赖级联同因组豁免判据（纯级联组不判拒不派重合成）、框架透传标记作豁免锚点防伪标申报、混合组仍拒语义保持、豁免决策随查重结果结构与验证日志留痕
