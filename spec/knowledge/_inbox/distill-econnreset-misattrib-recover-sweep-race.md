# 知识蒸馏三缺陷合订：ECONNRESET 被误归因「确定性拒识不重试」× 恢复重派被启动清扫误杀 × pending 台账只挂重启钩子

## 背景

2026-11-04 add-systemd-hosting 推送（11:31:14 入库）后，归档蒸馏管线自动派发 knowledge-distill run，
主蒸馏三撞网关瞬断（stdout `API Error: Connection dropped (ECONNRESET)`），两次被错误分类器判为
「确定性拒识，不重试」；重启恢复重派的 run 在创建 2ms 后被启动终态清扫补写 interrupted。截至当日 15:45
主蒸馏仍未完成，pending 台账滞留，只能等下次 daemon 重启续跑。

## 结论（当前事实）

- **误归因（重试被错误抑制）**：`_stderr_hits_unrecognized_model` 对已失败 run 的全量 stderr 匹配
  `unrecognized_model` 子串即判「拒识形态」；而该 stderr 行是 CLI 对自定义网关模型名的**启动期噪声**，
  glm/deepseek 链成功 run 同样在场（`core/knowledge.py:1136` docstring 与 `core/knowledge_backfill.py:983`
  自认）。`_spawn_with_reject_retry` 在显式传名分支直接断言「显式传名仍被拒属确定性失败，不重试」
  （`core/knowledge.py:2527-2546`），把 stdout 里真实的瞬断死因（ECONNRESET）盖成拒识终态。
  反证「确定性」：同车道 fold zn-inbox-entry-2 于 11:35 同型失败、11:57 同条目折叠成功；窗口内 fold 5/6 成功。
  真死因判别应看 **stdout 的 API Error 行**（瞬断）而非 stderr 噪声行。
- **启动顺序倒挂（恢复重派被误杀）**：`recover_pending` 挂在 `__init__` 尾部（`fenixd.py:785`），
  Startup terminal-state sweep 挂在 `start()` 头部（`fenixd.py:814`）。sweep 自述要求「任何派发与
  恢复派发之前」执行，实际晚于恢复重派：11-04 11:51:18.985 恢复重派创建 run
  `knowledge-distiller-add-systemd-hosting-1793764278`，.987（2ms 后）sweep 将其当「遗留无终态 run」
  补写 interrupted，该 run 从未真正起跑。当日旧 daemon 为干净排水（无在飞 run），sweep 找到的唯一
  「遗留」恰是自家刚派的新 run。
- **台账再驱动单点**：蒸馏 pending 台账的重派只挂 daemon 启动（`recover_pending`，dashboard --serve
  不接入）；主循环 300s 检查点仅做「登记超 24h」欠账提醒、不重派（`core/knowledge.py:1165-1175`）。
  主蒸馏失败若逢网关不稳（如本例连败两次），欠账滞留至下次重启。fold 子项有「滞留原地待下轮重试」
  的轮内自愈，主蒸馏没有等效物。
- **时间轴显示缺口**：dashboard `runVisual.ts` 的 `AGENT_LABEL`/`RUN_ID_PREFIX_LABEL` 未收录
  `knowledge-distiller` 车道（表早于 knowledge-atlas 车道建设），该车道 run 一律回退显示「未知 Agent」
  ——与当年 arbiter「未知 Agent」同型缺陷（同文件内 add-arbiter-quality-display 注释即先例）。

## 证据

- run 1：`.fenix/runs/archive/knowledge-distiller-add-systemd-hosting-1793763090.jsonl`
  （11:31:30 started → 11:46:04 error exit=1；daemon 日志 03:35:48Z/03:46:04Z/04:03:52Z 三次
  失败的 stdout 摘要均为 `API Error: Connection dropped (ECONNRESET)`）。
- run 2：`.fenix/runs/archive/knowledge-distiller-add-systemd-hosting-1793764278.jsonl`
  （started 11:51:18 → interrupted「startup terminal-state sweep」同秒）；顶层副本被 12:03 重试续写
  （`runs 保留: 顶层副本比归档副本新` 告警即此）。
- daemon 日志：`03:51:18.985Z 恢复重派（1 批）` → `03:51:18.987Z Startup terminal-state sweep: 补写 1 个`。
- 11:51:10 重启动因：陈旧自愈（daemon 持旧代码连续空闲 300s → restart_request），非 systemd 接管。
- 台账现状：`.fenix/knowledge-distill-pending.json` 仍存 add-systemd-hosting（queued_at 11:51:18）；
  `.fenix/todo.md:92` 重试行在案。

## 修复方向建议（供立项择选）

1. 分类器：失败 run 先看 stdout `API Error` 行判瞬断（可重试），仅当**无** API 流量痕迹（0 round +
   启动期即死）才采纳 stderr 拒识归因；「显式传名仍被拒=确定性」结论与 11-04 实证冲突，须重审。
2. 顺序修复：sweep 移回 `recover_pending` 之前（同一阶段内先 sweep 后恢复重派），或恢复重派跳过
   sweep 已收编窗口（如 run 文件 mtime 晚于进程启动时刻即豁免）。
3. 台账再驱动：给 pending 台账加运行期兜底重派（如随维护检查点周期驱动，带退避/龄期上限），
   摆脱「只等重启」。
4. 显示补表：`AGENT_LABEL`/`RUN_ID_PREFIX_LABEL` 收录 `knowledge-distiller`（知识蒸馏 Agent）。
