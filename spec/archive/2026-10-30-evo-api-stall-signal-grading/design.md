# 设计：api-stall-signal-grading

## 落点与现状

- 发射点：core/agent_runner/runner.py:6184-6198（run 循环内单轮延迟超 STALL_ROUND_WARN_SECONDS 即 WARNING，事件 api_round_stall）。
- 统计：core/agent_runner/latency.py —— LATENCY_STALL_SECONDS=60.0（:23，stalls>60s 统计口径）、STALL_ROUND_WARN_SECONDS=120.0（:36，告警线）、format_latency_summary（:206-209，汇总行渲染，调用点 runner.py:6694-6705）。
- 判停线：RUN_STALL_ROUND_SECONDS=120.0（runner.py:194，run-stop-loss 预算，缺省关闭）——本次不动。
- 终态行丢统计根因：run 档案行由 runner.py:6819-6847 构建且含 latency 三字段（latency 三字段持久化以构建处代码 :6836-6840 实证为准；proposal 引用的样本档案 code-review-1791997236.jsonl 经评审实测已不在本仓 .fenix/runs/archive/ 下——run 档案按项目根归集且可被清理，该引用仅作现象佐证不作机制依据）；成功终态日志行走 _log_run_metrics（runner.py:8687-8778），latency 参数可选，调用点无样本上下文时回退 0/0/None（:8710-8711、:8745-8747）。
- 摘要：core/self_review.py collect_daily_summary（:1651）；第 6 节 :1754-1794；初筛维度 MIDFLIGHT_OUTLIER_DIMS（:774）；深扫 _scan_run_midflight（:1088-1173）已复用 latency_samples_from_events+latency_stats 产 stalls/max_gap。

## 方案

1. latency.py 新增分级纯函数 classify_round_stall(streak, round_seconds)，返回 info / warning / warning-escalated；新增常量 STALL_ROUND_ESCALATE_SECONDS=300.0。规则：round>300 → escalated；streak≥2 → warning；其余 → info。streak 口径（评审补约定）：连续 = 相邻样本逐个 >STALL_ROUND_WARN_SECONDS（遇 ≤120s 样本重置计数），发射点由 latency_state["samples"] 尾部计得，classify_round_stall 保持纯函数。三既有常量取值与语义不动（modules contract 测试锁常量同源，新常量独立声明，不并入既有同源组）。
2. runner.py 发射点：>120 秒轮次先经分级——info 用 INFO 级落日志（事件仍 api_round_stall，context 增 grade 字段）；warning/warning-escalated 保留 WARNING。每 run 结束把分级计数传入 format_latency_summary 渲染（汇总行行尾追加 warning=N info=M；既有 stalls>60s 口径不变）。成功终态调用 _log_run_metrics 处把本 run latency 统计对象传入，消除 0/0/None 回退。数据通路（评审实测补约定）：stats 现为 _run_agent 局部量（:6695，latency_state 局部状态），_finalize_success（:5023，:5124 调 _log_run_metrics 未传 latency）不可直达——经 _run_agent（:5760，返回 tuple）把 stats 随返回值携带，成功调用点（:3804）传入 _finalize_success 新增参数，再以 latency= 传 _log_run_metrics；其余提前终态路径（无样本上下文，:8708-8711）维持零样本回退不动。
3. self_review.py 第 6 节末尾新增聚合行，逐 run 一行「- api-stall: <run_id> stalls=N total=Xs max=Ys」（stalls=0 不列；已被深扫覆盖的 run 允许重复出现，是否去重由实现者按实现代价决定，测试固定所选行为）。数据对当日 run 事件流复用 latency_samples_from_events/latency_stats，与深扫同源；不改 MIDFLIGHT_OUTLIER_DIMS、不改深扫行为。约定（评审补）：聚合环节随第 6 节既有降级契约（异常降级空产出 + warning，不阻断摘要与其余各节，对齐 :1754-1756 节头契约）；逐 run 扫描沿用深扫同款有界流式口径（MIDFLIGHT_SCAN_MAX_LINES 上限、逐行 json.loads，单行可数 MB，MUST NOT 整文件读入内存，对齐 :1096-1098）；「累计停滞秒」latency_stats 不直接产出（只有 stalls/max/ratio），取 samples 中 >LATENCY_STALL_SECONDS（60s）样本之和，与 stalls/max 同源自 samples。

## 风险与兼容

- 既有测试 tests/test_run_latency_stats.py 断言「单轮 >120s 打 WARNING」，需随新分级语义更新（属本 SPEC 交付，见 tasks 3.2）。
- 汇总行格式为日志与人读，无程序解析依赖（api_round_stall 全仓仅一个发射点、零消费者，grep 已核）。
- 不新增配置键；/root/fenixd/core 与 /root/fenixd/.fenix/core 两份 runner.py 当前逐字节一致（md5 相同），改动随主树部署路径走，无分叉风险。