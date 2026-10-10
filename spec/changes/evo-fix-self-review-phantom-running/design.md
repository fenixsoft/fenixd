# fix-self-review-phantom-running 设计

## D1 根因与方案取向（取证结论）

2026-10-11 只读取证（复算窗口 [2026-10-09T16:14Z, 2026-10-10T16:05Z]：total=22、running=8、succeeded=13、failed=1，与日报精确一致）确认：

1. 写侧无罪：4 个抽样幻影产物（impl-evo-self-review-todo-head-restore-1791572223-a1 / -a1-r1 等）末行均为 superseded——fix-retry-orphan-active-runs 1.1 的补写内核（runner.py:4307-4325，_in_place_retry_backoff_yield）工作正常，attempt id 构造（runner.py:3080）与原地重试换新（runner.py:3184）均按「补写 superseded 后再换新文件」执行。
2. 读侧缺口：_classify_run（self_review.py:390）终态词表只有 result/error，早于 superseded 终态引入（980865f1），未随词表演进更新。
3. todo 假设推翻：非「in-place retry 不回写原 attempt 终态」，亦非「多车道普遍缺终态回写」——spec-review×3、admin-fenixd-1791587146 产物末行均为 result（分类 succeeded），review-2026-10-10 被 review- 前缀排除（self_review.py:780-781），均不在 8 个之列。这些 run 在 fenixd.log 只有 context metrics 行而无终态 run_metrics 行属另一层面缺口（指标车道覆盖，活跃 SPEC evo-add-run-metrics-lane-baseline 辖区），不影响日报在跑计数。

因此方案是读侧词表对齐 + 残余对账，产物写侧零改动。

## D2 词表单源选择

- 复用 core.dashboard.data.runs.RUN_TERMINAL_STATUS_MAP（runs.py:299-312，公开名 :326）：result/error/interrupted/cancelled/frozen-terminated/superseded/gate-blocked 全集，dashboard classify_run（runs.py:330）与 core/code_review.py read_progress（:1291-1323）已在用。消费方式对齐本模块延迟导入风格（参照 _run_terminal_success，self_review.py:481），避免加载序副作用。
- 明确不消费 core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（liveness.py:132）：该集合故意排除 superseded（liveness.py:221-227 注释——superseded 写在退避 sleep 之前、窗口内没有别的文件代表该 run，判终态会造成双派发）。统计场景是事后回看（报告时刻距产物末行可差 21 小时），退避窗口语义不适用。两套词表差异 MUST NOT 被「统一口径」抹平。
- result/error 分支的既有业务失败语义（marker 声明窗口、终态邻近信号、超时/秒挂签名，self_review.py:407-443）逐字节不动——本条只填「其余终态词」的去向。

## D3 桶位与计数语义

- 新桶：superseded（弃置/重试件——同一逻辑 run 的中间弃置分片，最终结果活在后续分片）、ended（interrupted/cancelled/frozen-terminated/gate-blocked——已终结但非成功交付）、stale（无终态残留——D4 对账产物）。
- 不改计数粒度：每个产物分片仍计 1 个 run（维持与历史日报的可比性）；attempt 分片去重（按 _strip_run_attempt_suffix 归一计逻辑 run）列为非目标——它改变「总 run 数」语义，应另行立项。
- collect_runs_stats counts 初始 dict（self_review.py:571-579）同步补键——counts[category] += 1 对未知 category 即 KeyError，这是本条最大回归点，测试锁定。
- collect_failed_run_samples 仅 category=="failed" 入选（现状），新桶天然不入失败样本；用测试固化防回归。
- _is_phantom_signal_failure 守卫只对 failed 生效，与新桶无交互，不动。

## D4 残余 running 的 stale 对账

todo 建议的「子进程树/活跃 run 注册表活性对账」不采纳：归档产物（窗口内大多数已进 archive/）无进程可查，注册表只覆盖在飞 attempt，且引入 daemon 内部状态依赖。改用两个读侧确定性判据，均为现成单源：

1. _run_terminal_success（self_review.py:469-491）：run_metrics 指标 terminal 查询，已含 attempt 后缀对齐与轮转回退——产物断尾但指标记 terminal=success（daemon 崩溃截断收尾）的 run 按 succeeded 计。
2. RUN_STALE_SECONDS（runs.py:327 公开名，1800s）：mtime 停更阈值，取自 dashboard 读侧同款判据（runs.py:464/:511，跨包消费先例 core/code_review.py:1488-1489）——超阈值且查无指标终态 → stale；不足阈值 → 维持 running（真实在跑或近瞬状态，宁可不拦不可误伤）。

对账仅对 running 判定的 run 触发（终态 run 零额外 IO）；mtime 以统计时刻（window_end 快照）为基准。

## D5 渲染

第 2 节（self_review.py:1577-1591）在「丢弃/空」与「在跑/无终态」之间插三行：「弃置/重试件: N」「其他终态: N」「无终态残留: N」；「在跑/无终态」行保留（语义收窄）。形态为增量加行，不改动既有行文案，人工与下游对既有行的消费不受影响。