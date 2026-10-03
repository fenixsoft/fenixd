## Deliverables

```yaml
- path: core/adjudication_narrative.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/agent_runner/token_budget.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/dashboard/static/src/components/alert-shared.tsx
  kind: modify
- path: tests/test_adjudication_narrative.py
  kind: modify
- path: tests/test_narrative_sidecar.py
  kind: new
- path: docs/help/06-governance.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 证据采集器

- [ ] 1.1 `core/adjudication_narrative.py` 新增按 signal_type 的采集器注册表：验证族信号（judge_rerun_cap / inconclusive_loop / verify 预算与闸门族，注册表内显式列出）采集四段材料——`spec/changes/<spec>/verification-report.md` 全文、`report.json` summary + 失败/警告场景表（含 classification 分布）、`verdict_stability.json` rounds 历史、`fail_history.json` 轮次演进；全部 fail-open（缺失/损坏跳过该段）；总上下文预算 16K 字符分段截断（段界保留 + 截断标记）；prompt 注入【验证材料】段
- [ ] 1.2 `escalation_notifier` / `_send_human_escalation_alert` 及两个旁路发射点预留可选 `facts` 结构化参数位（本期缺省不传不注入，prompt 含 facts 段模板：存在时注入、缺省跳过）；MUST NOT 改动既有 trigger/choices 落盘形态

## 2. 四段 prompt

- [ ] 2.1 `_build_prompt` 输出结构升级：三段改四段（`发生了什么 / 调查结论 / 为什么需要你决策 / 决策选项`），REQUIRED_SECTIONS 常量与 `_validate_structure` 同步四段齐全且顺序不倒置；指令升级为「调查结论基于【验证材料】给出根因判断并引用具体证据（计数器/预算/环境事实）；材料不足以定位时明确写『材料不足以定位』并给出建议查证路径；材料内有据可依的因果推断必须给出，材料外事实不得编造」
- [ ] 2.2 `_clip_narrative` 分段预算从三段均摊改四段均摊（整体预算 8192 字符不变，段界锚定正则随 REQUIRED_SECTIONS 单源更新）

## 3. 异步补叙

- [ ] 3.1 `core/pm_engine/family.py` `_send_human_escalation_alert` 及 `core/worktree_manager/mergeback.py`、`core/agent_runner/token_budget.py`：`attach_narrative` 同步调用改为落盘后后台生成（threading.Thread daemon=True 或既有后台模式，任一告警发射点 MUST NOT 因叙事阻塞）；告警以机械文案立即落盘的既有时序零变化
- [ ] 3.2 补叙落点改侧车：`.fenix/admin_alerts_narrative/<alert_id>.json`（结构 `{"alert_id","text","model","at"}`，mkstemp + os.replace 原子写，目录不存在即建）；超时缺省 60→180（`DEFAULT_TIMEOUT_SECONDS` 与 ConfigLoader 单源注释、config.template.yaml 同步）；至多 2 次尝试（第 2 次失败 WARNING 后放弃）；人工已处置（handled）后补叙照常落盘
- [ ] 3.3 `core/dashboard/data/admin_alerts.py` 读侧合并：告警列表/详情按 alert_id 合并侧车 narrative 字段（字段形态与既有 `{"text","model","at"}` 一致，前端零 schema 变更）；侧车缺失时未 handled 告警附 `narrative_pending: true` 供占位
- [ ] 3.4 `core/admin_store.py` 告警清理路径（保留上限/归档清理）追加侧车级联删除；删除失败 WARNING 不阻断清理主流程
- [ ] 3.5 前端 `core/dashboard/static/src/components/alert-shared.tsx`：`narrative_pending` 告警渲染「调查生成中…」占位（灰态、不阻塞 choices 下拉）；既有 AlertNarrative 渲染确认四段 Markdown 兼容

## 4. 连续失败熔断

- [ ] 4.1 `core/adjudication_narrative.py` 模块级熔断器：连续失败计数（超时/空输出/结构校验失败）达 3 → 熔断 1 小时（窗口内生成调用直接跳过，零调用零延迟）；冷却到期或一次成功即复位；熔断生效/解除 WARNING 留痕；进程内状态不持久化；`admin.narrative_enabled=false` 时旁路

## 5. 配套测试

- [ ] 5.1 扩展 `tests/test_adjudication_narrative.py`：四段结构校验（含缺段失败走兜底）；采集器注入【验证材料】段（四产物齐备/部分缺失/非 verify 族三态）；16K 截断段界保留；facts 注入与缺省跳过；熔断器（3 连败跳过调用、成功复位、enabled=false 旁路）；超时 180 与 2 次尝试
- [ ] 5.2 新建 `tests/test_narrative_sidecar.py`（假通道注入，MUST NOT 真调网关）：告警先落盘后补叙（发射耗时不含 LLM 时延断言）；侧车原子写与读侧合并字段形态；handled 后照常补叙；侧车缺失 pending 标记；清理级联删除
