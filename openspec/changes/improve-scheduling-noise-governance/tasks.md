# Tasks: improve-scheduling-noise-governance

## 1. 验证环境健全性门（design D1/D2/D5）

- [x] 1.1 verify_engine 增加后置分类函数：识别「mock_api 存在 + 纯 Locator/wait_for 等待类断言错误」组合并触发环境探针（dashboard `/api/state` 连通+推流检查）；补单元测试（探针通/断两分支）
- [x] 1.2 场景结算接入 blocked-env 分类与 summary.blocked_env 统计；报告字段与既有 schema 向后兼容（旧 report 无该字段读为 0）；补单测
- [x] 1.3 verdict 换算接入：有效失败=failed-blocked_env；全批 blocked-env 判 inconclusive → 保持 testing 重派；inconclusive 轮次不累计 repeated_failures（信号抑制标记传递到 admin store）；补单测四例（含今日 fixture 期望值断言）
- [x] 1.4 今日真实 report 脱敏入库 `tests/fixtures/report_0827_noise.json`，回归断言：≥12 场景转 blocked-env、整体 inconclusive

## 2. 派发队列老化（design D3）

- [x] 2.1 _run_queue 条目结构加 enqueued_at；_process_queue/_on_spec_ready 比较改用 effective_priority 计算（config: pm.dispatch.aging.*，默认 enabled=false）；补单测（P6 饿死案例获得窗口 / 未达阈值零行为差异 / floor 封顶）
- [x] 2.2 同级稳定序保障与活动任务不老化；daemon 重启语义（重建队列从零计时）注释与单测

## 3. fix 族谱收敛（design D4）

- [x] 3.1 族谱度量函数（深度=fix- 前缀层数、宽度=同父未完成兄弟数，基于 read_all 全量）；_on_spec_bug_found 创建前接线拦截；补单测（四层请求拦截 / 宽度第二拦截 / 历史命名不追溯）
- [x] 3.2 family_explosion 信号接入 admin store 与 disposition 流程；「放行一次」豁免位 `_family_waiver` 设置/消费/复位；补单测（信号产生 / 放行单次通行 / 未放行持续拦截）
- [x] 3.3 config.yaml 增补 pm.family 与 pm.dispatch.aging 注释默认值；dashboard 无需改动的前提下确认 family_explosion 在既有 activity view 可见（手动冒烟）

## 4. 回归与核验

- [ ] 4.1 全量 pytest 通过（重点 tests/test_core.py、verify 相关及新增用例），无既有用例回归
- [ ] 4.2 对照三个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论
