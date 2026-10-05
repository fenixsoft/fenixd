# proposal: code-fix-api-timeout-salvage

## 背景

code-fix 批 run 跑在独立 worktree 里，单轮 API 请求超时（CLI 合成 "Request timed out" → Exit 1）会整轮判失败。现场核查（code-fix-1790453264，2026-09-26）：run 跑了 316 turns / 95 个 API 往返、约 43 分钟、10.15 美元后死于一次 1549.9 秒的单轮超时；工作树约 2 小时后被陈旧清扫删除，删除前 Pre-rmtree 快照机制用 git stash create 留下 commit 6e823fd7——该快照引用不入栈，是全仓无任何读者与恢复动作的悬空 commit，43 分钟级工作净损失。

## 问题

现有机制均接不住「一次超长请求超时即死」签名：

- code-fix 车道没有任何重试通路（core/agent_runner/maintenance_runs.py 的 run_code_fix 对 _run_claude 单次 try/except）；原位重试只在 spec 车道且要求 is_transient。
- evo-add-run-stop-loss 判「连续 ≥5 次 ≥120 秒或 stall 占比 ≥0.5」的慢死，本签名仅 1/95 个 stall 样本，且缺省关闭。
- Pre-rmtree 快照（core/worktree_manager/lifecycle.py _snapshot_dirty_worktree）只打「recover via」警告，三个调用点全部忽略返回值；且快照产生于失败约 2 小时后的陈旧清扫，彼时消化链已推进，快照注定悬空。

## 目标

- API timeout 终局签名结构化：失败记录与日志携带 api_timeout 标记，可判别、可追溯。
- 失败现场即时 salvage：命中签名且工作区脏时，把 WIP 以 salvage commit 落到批分支并按 recovery legacy 机制保全现场，而非坐等清扫后悬空。
- 现场被接续：同链下一批建树前消费 legacy，使重试批从 salvaged 工作起步。

## 非目标

- 不改 run_stall_budget 判据与缺省开关（评估结论：单轮超时终局无论如何终止于该轮，纳入判停不减少损失；「缺省开启」与 evo-add-run-stop-loss design 的灰度决策相悖）。
- 不动 spec 车道原位重试（fix-provider-transient-backoff）。
- 不动 Pre-rmtree 快照机制本身（保留为最后防线）。
- 不改失败后跳批推进的链语义（add-code-fix-batch-failure-selfheal）。

## 价值

签名复发即整批 40+ 分钟级工作蒸发（每个 300 轮级批次一次即全损）；salvage 基础设施（_salvage_commit、legacy 登记/消费）均已存在，改动面小、收益直接。