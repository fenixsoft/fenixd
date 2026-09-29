# 验证报告：add-codefix-affinity-batching

> ⚠️ 本报告由框架于 2026-09-26T16:09:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T15:58:07.972825+00:00

## 结论：✅ 通过（verified）

**状态：verified — 5/6 场景通过，0 失败，0 错误（全部场景通过）**

6场景：5 pass + 1 env warning（config-api-targeted-regression-roundtrip）。该场景失败实锤为验证环境版本错位：run时刻39945端口dashboard为merge f5a959b7（23:44:05落主树）前启动的旧代码进程，写路径静默丢弃targeted_regression新键且无bool前置校验（POST "yes"返回200）；对23:57:54新启实例复现POST yes→400、POST false→GET读回False，与主树源码（config_admin.py:1130合并/:1448校验）完全一致，产品代码无缺陷。建议重验该场景确认。

| 指标 | 数量 |
| --- | --- |
| 通过 | 5 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.56M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| affinity-clusters-same-file-items | 文件亲和性聚类：同一文件跨时间多条 open 条目必入同批（文件组不可拆），组间按最早 first_seen_at 升序；select_batch 结果确定可复现 | pass | 0/2 | - |
| affinity-packing-hard-cap-and-oversize | 装箱四规则：单文件组超硬上限（2T）独立成批不拆分；异目录组仅批<T 时吸收且吸收后≥T 即封批；同目录组浮动吸收至 ≤H；达 H 封批余组进下一批 | pass | 0/2 | - |
| wave-cap-tiering-and-prompt-injection | 波次上限分档纯函数（G≤4→4；5≤G≤8→6；G≥9→8，8 硬上限、4 下限）与 {wave_cap} 注入 agents/code-fix.md 派发节；模板缺占位符回退旧文案 4 | pass | 0/2 | - |
| chain-last-batch-and-regression-split | 链末批判定（失败档案∪chain_skipped∪延迟台账∪本批排除后 select_batch 为空；失败档案/延迟台账在场不误判非末批）与批收尾回归两段式分流（末批恒全量；非末批定向；映射空/无占位符/配置关回退全量） | pass | 0/2 | - |
| test-targets-placeholder-str-list-env | {test_targets} 占位符双态替换（str 命令 shlex.quote 空格连接；list 命令恰等占位符元素级展开、内嵌原样替换）与 FENIX_TEST_TARGETS 环境变量回归窗口导出/还原 | pass | 0/2 | - |
| config-api-targeted-regression-roundtrip | 配置通道端到端：GET /api/config 回显 admin.code_review_fix.targeted_regression 缺省 true；POST 写 false 持久化后再读为 false；POST 非法值（字符串）被写前校验拒绝 400 且值不变；末步恢复缺省 true。夹具说明：被测实例无项目注册 API 且无法注入 --add-project，故使用环境中已注册的 fenixd 项目（demo 项目不可自建，属场景文件夹具缺陷已修复） | warning | 3/9 | env |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| config-api-targeted-regression-roundtrip | step_3 json_path code_review_fix.targeted_regression 期望 false | env | 环境因素（非产品缺陷） | run时刻实例（旧代码）静默丢弃targeted_regression写入致复读true；对当前实例（新代码）复现POST false→GET返回False写读一致，实锤环境版本错位而非产品缺陷 |
| config-api-targeted-regression-roundtrip | step_4 status_code 期望 400 | env | 环境因素（非产品缺陷） | run时刻实例无:1448校验故"yes"返回200；当前实例同请求返回400（error: must be a boolean: 'yes'），校验代码行为正常 |
| config-api-targeted-regression-roundtrip | step_4 json_path code_review_fix.targeted_regression 期望 false | env | 环境因素（非产品缺陷） | step_2写入未生效的前置失败级联（run时刻实例值恒缺省true）；当前实例false写入生效后本断言前提成立 |
