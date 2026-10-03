# add-impl-wallclock-budget-sizing

## 背景

2026-10-03T12:34:12Z，potplayer-base 的 neutralize-pack-static-fingerprints 实现 run 第 1 次尝试（impl-neutralize-pack-static-fingerprints-1791030852-a1）烧满 12600 秒墙钟硬上限（9000＋2×1800，potplayer-base config.yaml:26-32）被击杀（exit_code -9，remaining_tasks=16），a2 复用同 worktree 再花约 876 秒收尾，实现车道被独占 3.5 小时。轮数维度已有 sizing 且已生效（evo-add-impl-run-budget-sizing：base=400→effective=800，a1 烧 607 轮未触轮顶）——约束已迁移到墙钟，而 timeout_supervision 的扩容判定（core/agent_runner/liveness.py:1200-1330）不含任何工作量维度（grep remaining_tasks 零命中；对比轮数路径 runner.py:2320-2357 已带）。另：被击杀尝试的 token/cost 无从回溯——provider（bigmodel.cn）逐轮 usage 恒零（a1 档案 607 条实测全 0），聚合 usage 只随 CLI result 事件落盘（core/agent_runner/runner.py:5730-5733，SIGKILL 无 result）。

## 目标

1. impl 车道墙钟预算 sizing：派发前按 spec 规模抬升墙钟续期预算（泛化框架内既有先例 fast-track higher 档 max_extensions 2→4，core/agent_runner/liveness.py:1249-1266），只抬不压、可覆盖可关闭。
2. 墙钟扩容判定纳入「剩余任务数 vs 剩余续期预算」：extend/kill evidence 与 timeout_extension 事件携带 remaining_tasks（与轮数路径 _turn_limit_action 同型）。
3. 击杀类终止的用量缺失显式化：kill 路径落「用量缺失注记」（cost 不可得＋原因＋transcript 规模粗估维度），消除静默黑洞。

## 非目标

- 不改轮数 sizing 既有语义（evo-add-impl-run-budget-sizing 已落地）。
- 不实现 provider 侧逐轮 usage 上报（黑洞的彻底消除依赖模型服务端，框架侧只做显式注记与粗估）。
- 不改 fast-track 车道既有加成行为；不改 absolute_max_seconds 封顶语义。

## 验收

- 大规模 spec 的 impl run 墙钟续期预算按 sizing 档位抬升；覆盖键优先；关闭时行为与现状逐位一致。
- 扩容/击杀 evidence 与 timeout_extension 事件携带 remaining_tasks。
- 击杀且无 CLI result 的 run 档案含用量缺失注记（原因＋粗估维度）；成功 run 落盘行为不变。
- 新增测试覆盖 sizing 归一化/阈值/覆盖键与扩容判定新分支；tests/test_impl_run_budget_sizing.py 既有 37 例不回退。