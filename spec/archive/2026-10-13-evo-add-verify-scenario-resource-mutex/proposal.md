## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 验证轮：effective_parallel=5（引擎缺省 Semaphore(5)，项目未配 max_parallel），回读主口径 pack2-ctest-roundtrip 与 win 交叉构建、cfc 模拟器等重型场景同批执行，高负载下默认档 mp4 瞬时缺 moov atom 判失败；两条 flaky 豁免记入 spec/changes/pack2-official-encoder/verification-report.md（14:01:52Z 合成），隔离重跑（88.95s Passed）由裁决 agent 手工补做。引擎 `_execute_parallel`（engine.py:369-480）只有并发槽与退避、无资源互斥语义；场景 schema（scenarios.py:1060-1090）无资源字段。batch-3 达 13-15 个场景池，多重型同批是结构性常态。

## 问题

1. 场景 schema 无资源维度，编排层无法表达「重型场景互斥/并行度约束」。
2. flaky 豁免记录不要求附同窗并行场景清单，复核归因缺证据（本案豁免理由的并行清单是裁决 agent 事后补写）。

## 方案

- 场景 schema 增加可选 `resource_group` 字段（缺省空=不受限）；`_execute_parallel` 同组在飞互斥——同组场景顺延到下一批，批日志与报告记录互斥等待标记与有效并发度。
- 提示词层：场景 schema 文档注册 resource_group 词表（权威源 scenarios.py），重型场景（交叉构建/模拟器/全量 ctest）同组；flaky 分类提示词要求豁免附同窗并行场景清单。
- 不改既有并发槽/退避语义；复用 depends_on 被否（失败传播污染归因）。

## 非目标

- 不做全局资源画像/自适应调度（只做静态分组互斥）。
- 不做 flaky 自动隔离重跑机制（本案重跑由裁决 agent 手工完成，是否框架化另行立项）。
- 不动 evo-add-verify-dispatch-single-flight 等编排层单飞语义（层级不同）。