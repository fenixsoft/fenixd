# 设计：stray-escalation-evidence-budget

## 改动点

1. core/worktree_manager/stray_wip.py — 体积明细段截断
   - 「条目体积(字节)」段（:2019-2020）套用与文件清单段（:296/:317-321 EVIDENCE_MANIFEST_PREVIEW_LIMIT）同型的头部 50 项截断＋「等 N 项」＋体积合计字节聚合。
   - 全量体积已有注册表单源（:1931 sizes_bytes 注记），evidence 只引注册表不内联全量。
2. core/agent_runner/prompt_builder.py — 注入侧上限
   - administrator 分支装配 {evidence}（:479）与 re.sub 填充（:496）之间加体量检查：超过上限（如 200KB）fail-open 截断＋「[evidence 已截断：原 N 字符]」注记，防其他信号类型同型撑爆。
3. core/admin_monitor.py — 处置失败兜底
   - interrupted 限次重派通道（:5217-5385，reschedule_max 定义 :1503-1505）扩展覆盖 terminal_reason=prompt_too_long 与 api_error_status=400 终态形态；重派时传递瘦身 evidence（依赖改动点 1/2 生效）。
   - 重派用尽后产生处置失败升级信号，落 ESCALATION 记录，保证派发失败重试扫描（:4881）可达。

## 数据流

散件越阈 → 升级信号构造（体积段截断＋聚合）→ Administrator 派发（注入侧上限兜底）→ 成功处置；失败（prompt_too_long/api_error）→ 限次重派（瘦身 evidence）→ 用尽 → 处置失败升级信号。

## 边界与权衡

- fail-open（截断优于拒绝）：处置拿到缩水的证据也比链路死透好；全量明细经注册表仍可追溯。
- 重派仅 1-2 次（沿用 reschedule_max）：防对同一坏信号重派风暴。
- 不改升级触发阈值与「同一集合只升级一次」语义——本 SPEC 只保证失败后有兜底出口，不再依赖指纹消失前的带外救援。
