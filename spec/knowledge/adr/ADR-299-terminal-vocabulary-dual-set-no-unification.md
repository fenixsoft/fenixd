# ADR-299：run 终态读侧词表双集合分治，统计用全集、存活用排除集，禁统一

date: 2026-10-30
status: accepted

## Context

run 产物终态 type 在读侧存在两套词表：`dashboard.data.runs.RUN_TERMINAL_STATUS_MAP` 全集（result/error/interrupted/cancelled/frozen-terminated/superseded/gate-blocked），与 `agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES` 排除集（result/error/interrupted/cancelled，故意不含 superseded——该词写在退避 sleep 之前、窗口内没有别的文件代表该 run，纳入存活判定会在原地重试退避窗内造成双派发，见 ADR-134）。自省日报的 `_classify_run` 只认 result/error 两词、未随词表演进，superseded 弃置件全部落入 running 判定：实测窗口 22 个 run 中 8 个（36%）幻影在跑，真卡死混入不可分辨。修复时面对的诱惑是把两套词表「统一口径」成一套常量。

## Decision

- 事后统计类读侧消费一律引用 `RUN_TERMINAL_STATUS_MAP`（或其键集）单源，禁止另立字面量词表；自省日报分类是其消费方之一（dashboard `classify_run` 与 `code_review.read_progress` 为既有消费先例），以模块内延迟导入消费、不引入加载序副作用。
- 禁止在任何统计场景消费 liveness 的 `RUN_TERMINAL_EVENT_TYPES`：其排除 superseded 是存活判定的刻意语义（防退避窗双派发），事后回看场景（报告时刻距产物末行可差小时级）该理由不成立，复用即把弃置件重新计成在跑。
- 两套词表的差异是「存活判定 vs 事后统计」的语义分层结果，禁止以统一口径、合并常量、提取公共集合等名义抹平；`result`/`error` 分支既有的业务失败语义（marker 声明窗口、终态邻近信号、超时/秒挂签名）不受词表扩展影响。

## Consequences

- 词表演进单点生效：框架未来在 `RUN_TERMINAL_STATUS_MAP` 新增终态 type，统计侧无需改动即不误计 running。
- ADR-134 的存活侧裁定继续独立成立：liveness 排除 superseded、末行终态判死、恢复语义单实现点均不受本 ADR 影响。
- 任何想合并两集合的消费方改动须显式 supersede 本 ADR，并同步复核 ADR-134 的双派发边界（合并词表到存活侧=退避窗双派发回归，合并到统计侧=弃置件幻影在跑复发）。
