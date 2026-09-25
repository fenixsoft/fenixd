## 待办（人工登记 2026-09-24）

- [ ] code-review run 取消（cancel）终态不做产物抢救落账：2026-09-24 run code-review-1790230628 取消后 inserted=0/shards=0，101 文件 45 条发现留在 out 文件需手工 `_read_code_review_out`+`upsert_findings` 补账；error 路径有抢救（1b83c1c1）而 cancel 路径没有，应统一收场抢救。
- [ ] code-review 主车道 ocr scan 网络僵死无护栏：opencodereview scan（101 文件并发 4）2h20m 仅 49s CPU（0.5%，纯网络等待），agent 轮询等待且被处决后「重试重启 scan」而非按提示词「ocr 不可达降级继续」收口，最终靠人工 cancel 脱困；应对 scan 加 CPU/时长心跳判据 + 不可达降级收口（与 ocr 车道心跳方案 prio4 同族）。

## 2026-09-25

### 浪费
- **主树WIP重叠全天5次挡合回、2批弃现场、3次人工救场**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：全天 5 个 implementer/code-fix 分支的合回（merge-back，把工作分支并回主树）被 WIP 重叠预检（主树存在与分支同文件的未提交改动时阻止合回的闸门）先后挡下，每次放行等待 20-47 分钟、累计约 2.1 小时；另 2 个 code-fix 修复批次因合回冲突「现场即弃」（丢弃整批工作现场、仅存档分支名）整批作废重跑，全天消耗 3 次显式人工收编提交救场。
  - 证据：daemon 日志 ERROR 时间线（本地时间）：10:37 告警 add-code-review-trigger-ack 被阻、10:49 add-code-review-concurrency-and-429-resilience（重叠 2 文件）、12:43 code-review-fix-1790223760、14:28 与 14:45 code-review-fix-1790230556 两次、17:11 code-review-fix-1790239507；放行均靠主树 WIP 被人工提交——5a5f6595（11:12 收编无主实验 WIP）、29d3945c（12:57 提交 batch 7）、c030d19a（17:21 admin 收编提交）、738cbf0d（15:05 质量页签 UI 修正顺带放行 14:28 那次）；另有 11:32 与 17:34 两次「code-fix 第 4/第 2 批合回冲突，现场即弃」日志。
  - 调查评估：在处置 code-review 台账修复批次与 add-code-review-concurrency-and-429-resilience 合回时暴露。已核实事实见上，与 admin_alerts 中 mergeback_wip_overlap、code_fix_wip_gate_deferred 告警交叉一致。根因是主树长期携带人工/实验未提交改动（dashboard 静态页、agent-env-overrides 实验），与 code-fix 提速后「高频小批、批批合回」的吞吐模式结构性冲突，不是单次执行失误。与存量工作关系：当日已落地两个对症 spec——evo-add-codefix-batch-wip-precheck（fc752705，选批前预检重叠则整批推迟）与 evo-add-wip-defer-merge-retry-consumer（5b1f0581，阻断落结构化载体后由 120 秒周期消费者自动合回、90min/6 次有界降级），18:32 后窗口内无新复发，但两修复均合回于 daemon（16:45 启动）之后、未重启未生效（见改进项），护栏目前空转。结论：该家族已被正确收口、无需新 SPEC，缺的是让修复生效加短期观察。
  - 建议：无需新 SPEC；先重启 daemon 让两个已合回护栏生效，观察 48 小时——若 mergeback_wip_overlap 告警清零、code_fix_wip_gate_deferred 能被周期消费者自动闭环即关闭本家族；若频繁走到 90min/6 次降级再立项收敛。


## 2026-09-26

### 浪费
- **并行出题无产物空耗59分钟，串行重出再花3.3倍成本**
  - 影响：add-regression-auto-fix（回归自动修复 spec）的出题阶段两连失败：并行 planner（出题 run）跑了约 59 分钟、83 轮 API 往返后退出码 0 却无结果文件，整跑作废；串行重出再耗 $9.57（同组中位 $2.86 的 3.34 倍）与 47 分钟墙钟，其中 10% 往返停滞超 60 秒。该 spec 从合回被阻到最终 push 共拖延 1 小时 44 分。
  - 证据：并行 run planner-plan-add-regression-auto-fix-1790308587-a1（11:23 本地派发，83 轮、median 6.7s、4 次>60s 停滞单次最长 165.6s）12:21 被仲裁判「testing 等待并行出题超时，半成品隔离」，产物硬门同刻报「exit 0 但结果文件缺失」；串行重出 run planner-plan-add-regression-auto-fix-1790310119-a1（12:21-13:09 本地）终态 115 轮、stalls>60s=11（10%）、max 215.5s、cost_usd=9.572714，成功收尾。
  - 调查评估：在处置 add-regression-auto-fix 的合回阻塞恢复链中暴露：11:59 本地 mergeback_wip_overlap（合回主树前的 WIP 重叠预检告警）阻断 → admin 处置 run admin-add-regression-auto-fix-1790309003（管理员通道处置，40 轮）→ 12:21 并行出题超时隔离、转串行重出 → 13:43 push。已核实两条 run 的指标行与终态如上；串行 run 深扫的中途 stderr unrecognized_model（claude CLI 对代理模型名的输出告警，全日志仅 2 处）与停滞无因果，已排除。根因是无 run 级停滞/无产物止损：并行方僵死只能等「并行出题等待超时」仲裁兜底（59 分钟后），产物硬门 add-judge-artifact-gate（出题产物存在性裁判）只在收尾拦截，串行重出又全程顶上 provider 慢周期（11 次停滞）。与存量工作：add-self-review-midflight-signals（中途信号浮现基建）只把离群浮出到日汇总、不参与处置，evo-fix-transient-break-unseal-backoff 针对断连退避而非慢停滞，双 planner 并行仲裁本身按设计工作——残余缺口即「停滞预算提前止损」，互补不重复。结论：值得立项小 SPEC。
  - 建议：立项「长 run 停滞预算」：run 内 stalls>60s 计数或累计无产物时长超阈值（如 ≥8 次或累计 >10 分钟）即有序 abort 并转串行/在 run 边界 resume，判据复用 midflight-signals 已有指标输出，避免 59 分钟级空耗与 3.3 倍成本重演。

- **（新增）主树WIP重叠再挡1次合回，48小时观察期继续**
  - 影响：修复加载前的旧代码再挡 1 次合回（add-regression-auto-fix），该 spec 从被阻到 push 拖延 1 小时 44 分并消耗 2 次 admin 处置；23:50 最终重启加载新护栏后至今（约 2.5 小时，含 60+ 提交的晚间批次风暴）零复发。
  - 证据：03:59:33Z mergeback_wip_overlap 告警（合回 WIP 重叠预检，add-regression-auto-fix 与主树同改 core/code_fix.py，policy=escalate）；处置 run admin-add-regression-auto-fix-1790309003 于 04:15 收尾；当前主树仍带 .fenix/verify.yaml、tests/test_artifact_paths_declaration.py 两处未提交修改与 TODO.md 删除。
  - 调查评估：在处置 add-regression-auto-fix 合回阻塞时暴露。已核实：该次阻断发生于 15:38（本地）自愈重启之前，09-24 合回的两个护栏（evo-add-codefix-batch-wip-precheck 选批前重叠预检、evo-add-wip-defer-merge-retry-consumer 周期合回消费者）尚未加载，属昨日悬空期的尾声复发；15:38 与 23:50 重启后，晚间 21:12-23:41 的 60+ 提交 code-fix 批次风暴全程零阻断，选批预检经受了实战。根因（主树长期携带人工/实验未提交改动）仍在：主树现存两处修改与一处删除未收编。结论：按昨日建议维持 48 小时观察（至 09-27 23:50），期满且 mergeback_wip_overlap 告警清零、code_fix_wip_gate_deferred 能被周期消费者自动闭环即关闭本家族，无需新 SPEC。
  - 建议：观察至 09-27 晚，零复发且自动消费者路径经实战即关闭本条目；主树现存未提交改动尽快收编或 stash，削减残余敞口。

### 失误
- （当日无）

### 可改进
- （当日无）
