# 设计：自省 run 成功判据纳入业务失败语义

## Context

core/self_review.py:150-172 `_classify_run` 按终态事件类型分类：`result`→succeeded、`error`→failed/timeout/instant_hang、无终态→running、空文件→dropped。`collect_runs_stats`（:180）据此聚合。scheduling-showcase 12 个盲派 run 终态都是 result（进程正常终结、run 结果自述业务失败），被计入 succeeded——终止态≠成功态。

## Goals / Non-Goals

- **Goals**：run 级统计反映业务成败（SPEC 内容缺失/预算耗尽/零交付计失败），自省不再低估浪费；失败样本可追溯。
- **Non-Goals**：不做 NLP 语义理解（用结构化标记清单 + 结构性信号双源）；不改 run 产物写入格式（除非发现 result 文本无结构化标记等价物时做最小补充）；不新增统计 schema 字段以上层 UI 改动。

## Decisions

### D1：业务失败判定用标记清单 + 结构性信号双源

**选择**：以 result 文本命中设计固化的业务失败标记短语（SPEC 内容缺失 / 无法实现 / 预算耗尽 / 零交付）为主判据，以同一 run 的 budget-exhausted / spec_content_missing 类结构性事件为补充信号（主判据缺失时兜底）。

**理由**：实证 run 的 result 文本含明确的自然语言失败声明（『SPEC 内容缺失，无法实现』），标记清单可精确命中；结构性信号提供双源护栏防漏判。

### D2：判定不依赖具体运行时代码路径

**选择**：判定只读 run 产物文件（result 文本 + 事件序列），不接运行时的 spec_integrity/budget 对象（避免循环依赖与运行时状态漂移）。

**理由**：自省审核应基于落盘产物；离线可测。

### D3：失败类别复用既有 failed 槽位

**选择**：业务失败归入既有 `failed` 类目，detail 携带命中标记；不新增顶层类目（避免统计 schema 外层兼容面扩大）。

**理由**：输出 schema 兼容是 Non-Goal 约束；detail 字段可追溯。