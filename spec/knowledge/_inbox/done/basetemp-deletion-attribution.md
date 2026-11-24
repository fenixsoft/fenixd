# pytest-basetemp 共享根删除源定位（2026-11-22 00:19 全量回归 907 例假失败）

- 日期：2026-11-22
- 类型：排查结论
- 关联：`tests/conftest.py` 生命线修复链（687b722c6→1f44d155a）；`_inbox/code-fix-lane-safe-stop-procedure.md`

## 结论

删除者 = **每日自省 agent 的验证复跑**：`2026-11-21T16:12:06.977Z`（+0800 即 11-22 00:12:06）在主树 `/root/fenixd` 裸跑
`python3 -m pytest tests/test_timelib_guard.py -q -p no:cacheprovider`（闭环核验「2026-11-21#可改进#2」，结果 `18 passed in 8.02s`，
`.fenix/runs/archive/review-2026-11-22.jsonl` line 29/31/33）。

## 机制（事故时点生效的 conftest = c61033f5d，2026-11-16）

1. 任何未显式 `--basetemp` 的 pytest 会话，conftest 兜底 `_given_basetemp = <root>/.fenix/pytest-basetemp`——与
   `bin/run_full_suite.py:67 BASETEMP_REL` **同一 plain 共享根**；
2. pytest given-basetemp 语义：会话首次 getbasetemp 先 **rm_rf 清空**该根（全量回归在飞用例的 tmp 子目录全没）；
3. 会话收尾 conftest `shutil.rmtree(base)` **无条件删根**（今版已改为只清自建 pid 唯一根）；
4. 幸存的全量回归 `TempPathFactory` 缓存 `_basetemp` 不重建 → 此后全部 tmp_path 用例 setup ENOENT。

## 时间线（daemon 日志 + run 归档交叉）

- 16:03:55.92Z 周期回归获主机锁（run_id=regression-1795277035，11055 例）；
- 16:03:56.76Z 每日自省 prompt 启动（**daemon 午夜重启同时触发两者**，碰撞为排程必然）；
- 16:12:06.98Z 自省发 timelib 复跑（窗口内唯一 pytest 会话，supervisor.log 证实在飞 claude agent 仅此一个）；
- 16:12:15Z 复跑收尾 rmtree 删根；16:12:18.18Z 工具结果返回 18 passed；
- 16:19:45.36Z 全量回归完成：failed，907 例 basetemp ENOENT（= 删除点之后的所有 tmp_path 用例）。

## 已闭合的修复（当日 code-fix 批次 687b722c6→1f44d155a）

兜底根改 pid 唯一（`pytest-basetemp-<pid>`）+ 共享根不再收尾删除 + `_ensure_basetemp_alive` 双层生命线；
机制已闭合，无需再动排程。次生教训：根因类批量失败先停车修根因，勿逐条派批（见关联停车程序笔记）。

## 补充：非孤例，连爆两晚；为何此前长期无害

- **同一杀手、同一命令、连续两晚**：11-21 00:07:50 自省同样裸跑 `pytest tests/test_timelib_guard.py -q`（review-2026-11-21.jsonl line 41），
  落在 16:01:04–16:14:39Z 回归窗口内 → 11-21 00:14 全量回归 16% 批量 setup 假失败（修复版 conftest docstring 所引「2026-11-21 16%」事故）。
  台账首批 778 条 stale 条目正是该晚产物；11-22 00:12 复跑为核销该 timelib 条目 → 再爆 907 例。今晨用户所见是第二晚。
- **为何 11-21 之前从未发生**：review-2026-11-10..20.jsonl 共 11 个夜晚自省 **0 次 pytest 调用**（复跑核销是 11-21 起才出现的行为，
  源头是台账出现需「当场复跑」取证的 timelib 守卫条目）。碰撞三要素（00:00 周期回归 × 00:00 自省 × 自省主树裸 pytest 落入 ~14min 回归窗）
  此前缺一，故两个月未爆；凑齐后两晚连爆。
