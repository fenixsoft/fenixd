# 场景资源组互斥

<!-- knowledge: capability=verify-scenario-resource-mutex rev=1 sources=spec/archive/2026-10-13-evo-add-verify-scenario-resource-mutex -->

验证并行执行的资源维度约束：场景经 resource_group 静态分组实现组内在飞互斥，重型场景不再同批互相挤占资源；flaky/env 豁免强制附同窗并行证据，保复核归因可查。

## 规则

- 场景资源组字段：`resource_group` 是场景顶层可选字段，缺省空串 = 不受限；from_dict/to_dict 透传（round-trip 保持），未知键兼容不受影响。解析仅接受字符串形态，非 str（dict/bool/数字/null）一律归一空串、按未标记放行——错误形态的组名不报错打回，不制造新验收失败模式。组名为任意非空字符串（建议 kebab-case，如 heavy-build、emulator）。
- 同组在飞互斥：并行批调度时同 resource_group 场景互斥——本批已接受某组场景时，同组其余就绪场景自动顺延到下一批。顺延只挪批不改判失败归因（场景留在剩余集，下批就绪判定自然重入，最终照常执行）；等待发生在 Runner.execute 启动之前，不计入场景超时；互斥仅对非空组生效，空组名零开销直通；每批至少接受一个场景，无活锁。
- 跨组与未标记零变化：不同组之间、组与未标记场景之间同批照常并行，各组互不等待，调度与并行度不受互斥影响；场景集全部未标记时，调度、并行度与报告格式与无该能力时完全一致（report 顶层零新增键）。
- 互斥可观测数据以新键承载：报告顶层 `resource_mutex`（deferred_total=全轮同组顺延累计批次数、observed_parallel=全轮最大批实测并发），仅本轮存在资源组标记场景时写入；场景结果附 `mutex_waited`/`mutex_wait_batches`（仅被顺延过的场景落键）与 `parallel_context`（batch/peers/observed_parallel）。既有顶层 `effective_parallel` 语义不变（正常轮=配置值、降档轮=inconclusive 降档 override 值），实测并发 MUST NOT 原地改写该键。
- 豁免须附同窗并行上下文：flaky/env 豁免条目必须附同窗并行场景清单（同批执行的场景 id）与有效并行度。引擎对每个执行的场景统一附加 `parallel_context`（依赖失败跳过等合成路径同样覆盖），作为豁免复核归因的确定性证据源。
- 豁免证据不全确定性标记：报告合成层对缺 parallel_context 的豁免条目落「证据不全」标记——场景级 flaky/env 分类行与断言级豁免清单两处同口径；缺该字段的报告（含历史报告）一律带标记，如实呈现而非粉饰。提示词层是要求、报告合成层是可复核兜底，验收不依赖提示词遵从。
- 词表注册单源防幻觉：planner 出题提示词的场景 schema 文档段注册 resource_group 词表，权威源标注 core/verify_engine/scenarios.py 的 TestScenario.resource_group（字段语义与写端归一口径以源码为准，不自造同义字段名）；重型场景（交叉构建、模拟器、全量 ctest、长视频编码等高负载场景）标记同一组以互斥；flaky 分类提示词写入豁免附并行清单的强制要求。

## 关键行为

- 批调度顺序：依赖满足集 → 依赖失败传播摘除（合成 blocked-env 结果）→ 资源组互斥分拣（accepted/deferred，组名空直接接受）→ 并行执行；被顺延过又遇依赖失败的场景，其合成结果同样回填互斥等待标记，deferred_total 不丢账。
- 顺延发生时批日志记录顺延场景清单与在飞组，供批级追溯。

## 溯源

- 2026-10-13 evo-add-verify-scenario-resource-mutex（spec/archive/2026-10-13-evo-add-verify-scenario-resource-mutex） — 新建本页：场景顶层可选字段 resource_group 与写端非 str 归一、并行批调度同组在飞互斥（顺延只挪批、等待不计超时）、resource_mutex/mutex_waited/parallel_context 新键承载与 effective_parallel 语义冻结、planner 词表注册与 flaky/env 豁免附同窗并行上下文（报告合成层「证据不全」确定性标记）
