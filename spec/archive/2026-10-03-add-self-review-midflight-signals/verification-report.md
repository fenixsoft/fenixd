# 验证报告：add-self-review-midflight-signals

> ⚠️ 本报告由框架于 2026-09-25T04:23:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T04:23:59.152075+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.50M |
| 本链增量 Token（输出） | 0.13M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| midflight-unit-suite-full-pass | 运行新增测试套件 tests/test_self_review_midflight.py 全 21 例（初筛/深扫/痕迹归集/第六节注入四类单元行为）全部通过。出处：core/self_review.py:649、tests/test_self_review_midflight.py | pass | 0/10 | - |
| midflight-screen-outlier-success-run-selected | 量化初筛集成：4 个终态成功的 implementer run（中位 turns=10）中 turns=45 者入选并附组中位对照，其余 3 个不入选——成功收尾不豁免离群。对应 spec Scenario「成功但轮次离群的 run 入选」。出处：core/self_review.py:733 | pass | 0/10 | - |
| midflight-screen-small-group-skip-with-control | 初筛边界：组样本 <3 时跳过不判离群（同命令内置 3 样本组阳性对照照常检出，证明是口径跳过而非采集器失效）；cost_usd 全组缺失维度跳过不产假离群。对应 spec Scenario「样本不足组不判离群」。出处：core/self_review.py:661、780 | pass | 0/6 | - |
| midflight-screen-window-and-missing-index-skip | 初筛口径：run_id 内嵌时间戳早于窗口的 run 不参与初筛（其 9999 轮指标在场却不检出）；run_metrics 索引查不到的 run 跳过且不报错；窗口内阳性 run（turns=500）照常检出。出处：core/self_review.py:696、763 | pass | 0/5 | - |
| midflight-scan-stall-stderr-error-collected | 深扫集成：离群成功 run 的真实 stream-json 形态事件流（3 次 >60s 相邻工具往返停滞、1 条中途 error、2 条 stderr）被流式扫描采集：stall=3、max_gap=100.0s、计数与首条摘要正确。对应 spec Scenario「成功 run 的中途停滞被深扫发现」。出处：core/self_review.py:821 | pass | 0/9 | - |
| midflight-scan-20k-line-truncation-boundary | 深扫行数上限：恰 20000 行不截断（truncated=false），20005 行在第 20000 行停止并标注 truncated=true，全程不抛异常。对应 spec Scenario「超限截断不阻断」。出处：core/self_review.py:668、853 | pass | 0/4 | - |
| midflight-rescue-traces-grouped-noise-excluded | 编排救回痕迹归集：窗口内 provider switched=2、in-place retry=7、gave up=1 按关键词分组计数，每组样本截断至 5；泛词 retry（event_bus）、关键词命中但组件错配、坏 JSON 行、窗口外行全部零卷入。出处：core/self_review.py:689、939 | pass | 0/9 | - |
| midflight-summary-section6-mixed-render | 摘要注入集成：混合信号夹具（turns 10/12/90、成功离群 run 带停滞转录、换道与 gave up 痕迹）下，collect_daily_summary 第六节三小节完整渲染（含「成功收尾」标注、stall/max_gap/中途 error 计数、痕迹计数与样本），既有五节全部保持。出处：core/self_review.py:1323、1332 | pass | 0/15 | - |
| midflight-summary-empty-placeholder-stable | 空态形态稳定：空夹具项目（无 run、无痕迹）下第六节渲染占位行「（窗口内无中途信号）」，不渲染任何小节，自省流程与其余五节正常完成。对应 spec Scenario「全部信号为空时摘要形态稳定」。出处：core/self_review.py:1359 | pass | 0/9 | - |
| midflight-degrade-warnings-sections-intact | 采集器故障降级：初筛与痕迹归集环节抛异常时，第六节降级为空产出、logger.warning 留痕（含异常原文），collect_daily_summary 正常返回且其余五节不受影响。对应 spec Scenario「索引不可用时自省照常」。出处：core/self_review.py:1340 | pass | 0/10 | - |
| midflight-readonly-no-file-writes | 只读铁律：夹具项目预热一次采集后快照文件树，二次采集零新增零变更文件（既有 admin store 首读的惰性锁文件经预热隔离），且第六节照常产出痕迹内容——中途信号采集不写 run 产物、不触发任何写操作。出处：core/self_review.py:1334 | pass | 0/5 | - |
| midflight-prompt-doc-and-constants | 提示词与常量落点：agents/self-review.md 含第六节语义说明与 waste/improvements 条目引导（成功 run 中途浪费可立项、不产生告警只作证据）；core/self_review.py 含倍数 3、最小样本 3、行上限 20000 三常量与「关键词→组件」模式表。出处：agents/self-review.md:36、core/self_review.py:657、689 | pass | 0/11 | - |
| midflight-latency-reuse-contract | 复用契约回归（零改动复用面）：core.agent_runner.latency 的生成器入口可消费、stall 阈值仍为 60.0s、tool_result 识别契约不变——深扫 stall 采集正确性所依赖的三个前提。出处：core/self_review.py:834、core/agent_runner/latency.py | pass | 0/7 | - |
| midflight-existing-self-review-regression | 五源回归：既有六套自省测试（调度/窗口快照/终态交叉核对/结果分类/run 语义/归档统计，共 135 例）全部通过——第六源接入未改 _classify_run 口径与五源摘要结构。出处：tests/test_daily_self_review.py 等 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

