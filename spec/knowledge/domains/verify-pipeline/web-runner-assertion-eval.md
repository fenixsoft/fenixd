# web_runner 断言求值时机分层与视图快照归因

<!-- knowledge: capability=web-runner-assertion-eval rev=1
     sources=spec/changes/evo-web-runner-assertion-eval-timing -->

web_runner 验证引擎的断言求值编排规则：交互可用性类断言在视图切换感知的求值窗口内即时求值，流程级断言保持后置统一求值；交互断言失败载荷附视图快照供 judge 归因。

## 规则

- **求值时机按类型分层**：断言求值计划按断言类型分桶。交互桶为第 2 层交互可用性类封闭枚举（no_click_interception、no_overlap、in_viewport、z_index_order，单源 `WEB_ASSERTION_LAYERS` layer=2）；流程桶为其余全部断言（no_console_error 等），保持全部步骤执行完后统一求值的语义不变。
- **交互桶求值窗口（视图切换感知）**：逐步骤完成点探测各未决交互断言的目标元素可见性，于「目标元素仍可见的最后一个步骤完成点」即时求值（trial click 同步在该点执行）。场景步骤中途切换视图（如导航进会话视图后应用页被隐藏）时，交互断言在目标元素仍可见的时刻完成求值，不在错误视图下误报 not visible。
- **全程不可见回退后置**：交互断言目标元素自始至终不可见（元素缺失或真实缺陷）时，回退既有后置时机求值判失败并附视图快照——真实缺陷不被提前求值掩盖。
- **分层由引擎自动判定**：类型判定读断言声明对照封闭枚举，场景文件零改动、不新增断言 schema 字段（Assertion schema 仅 type/selector/label/expected/threshold/extra，无步骤绑定字段；选择器匹配式步骤绑定对现网 no_click_interception 语料全量落空，不采用）。
- **窗口内失败不中断步骤**：交互断言在其求值窗口内判定失败不中断后续步骤执行（断言失败不停步骤），结果按断言声明序回填 assertion_results；断言失败取证截图触发条件与视觉对比时机不变。
- **失败载荷视图快照**：交互断言报 not visible 等失败时，失败载荷附求值时刻的页面视图状态快照——当前可见视图、目标元素所在视图、可见性判定依据；快照为轻量 DOM 摘要形态，不以截图为默认载体。judge 据此区分「元素被遮挡」（trial click 报 intercepts pointer events，附同视图判定依据）、「元素随视图切走」（目标元素所在视图非当前可见视图）与「场景真实缺陷」。

## 代码锚点

- 主实现：`core/verify_engine/web_runner.py`（断言求值计划分桶与求值窗口编排）、`core/verify_engine/assertions.py`（trial click 执行与失败载荷视图快照）
- 断言层单源：`core/verify_engine/scenarios.py:WEB_ASSERTION_LAYERS`
- 守卫测试：`tests/test_web_runner_assertion_eval_timing.py`

## 溯源

- 2026-11-16 evo-web-runner-assertion-eval-timing（spec/changes/evo-web-runner-assertion-eval-timing/） — 新增本页：断言求值时机按类型分层（交互桶视图切换感知求值窗口、流程桶后置不变）、全程不可见回退后置、交互断言失败载荷视图快照归因。背景：断言批后置统一求值使导航切视图类场景的 no_click_interception 在错误视图下求值，同族误报跨轮再生 3 例、耗 rerun 修复轮 ≥3。
