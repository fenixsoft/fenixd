## Why

自省 run 聚合 `_classify_run` 的成功判据只看终态事件类型（`t == 'result'` 即 succeeded，core/self_review.py:164），不解析 run 结果内容。scheduling-showcase 实证：12 个盲派 implementer run 因空 spec 失败（run 结果自述『SPEC 内容缺失，无法实现』），但因其进程正常终止（result 事件）被自省统计为『成功 11 / 失败 0』，浪费规模被系统性低估、闭环判定被误导。任何真实项目的『正常终止但业务失败』run（SPEC 内容缺失、预算耗尽、零交付、空跑）都会落入同一失真口径。

## What Changes

- `_classify_run` 对 result 型终态解析 result 文本的业务失败语义：识别『SPEC 内容缺失 / 无法实现 / 预算耗尽 / 零交付/零产出』等结构化业务失败标记，归入 failed（或新增 abandoned 类目）而非 succeeded。
- 业务失败标记以设计固化清单 + run 文件 result/error 双源交叉（result 文本含标记 或 同一 run 有 budget-exhausted/spec-missing 关联信号即判失败）。
- 无 dashboard UI、无新配置键；统计输出 schema 兼容（沿用 succeeded/failed 类目，不新增 UI 依赖）。

## Capabilities

### New Capabilities
- `self-review-run-semantics`: 自省 run 成功判据纳入业务失败语义，终止态与成功态解耦

### Modified Capabilities
无 requirement 级修改：聚合口径输出 schema 不变。

## Impact

- **core/self_review.py**：`_classify_run` 增加 result 文本业务失败语义解析。
- **tests/**：盲派/空跑/预算耗尽 run 计分类别的确定性单测。