## Deliverables

```yaml
- path: core/verdict_check.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/planner-judge.md
  kind: modify
- path: tests/test_verdict_credibility_gate.py
  kind: modify
- path: tests/test_incident_replay_credibility.py
  kind: modify
- path: tests/test_verdict_dedup_resynthesis.py
  kind: new
```

## 1. 查重归一化细分与级联豁免（core/verdict_check.py）

- [x] 1.1 `_normalize_attribution` 扩展：从 `first_failed_step` 拆出失败步骤序号（正则提取「步骤N」/「step N」前缀）单独进指纹；描述体截断哈希保留；断言 triage 的 assertion label（type+selector）确认在指纹内
- [x] 1.2 级联豁免判定：被比对场景组 classification 相同、描述体归一化后前缀重合 ≥80%、但步骤序号集合或断言清单逐场景不同 → 该组不计违规；纯同文（步骤序号也相同）仍拒
- [x] 1.3 单测（tests/test_verdict_credibility_gate.py 扩展）：「共享根因+各异步骤」放行、「共享根因+同步骤同文」仍拒、2/3/4 场景边界、豁免只对同 classification 生效
- [x] 1.4 回归：tests/test_incident_replay_credibility.py 既有查重用例全绿（模板偷懒拦截语义不回退）

## 2. 拒后重合成回路（core/pm_engine/verification.py）

- [ ] 2.1 `batch_attribution_dedup` 拒绝分支（首轮 3225 附近 + 重试轮 3400 附近两处统一收口到一个 helper）：调 `_write_verdict_violations` 落盘违规（条目含 scenario_ids 列表与重合成指令 reason）+ 写 `dedup_resynthesis_directive.json`（被拒场景清单、逐场景现有归因文本、失败步骤序号/断言 label 差异化素材）
- [ ] 2.2 新增重合成派发方法：复用 `run_planner(spec_name, "judge")`，处理 frozen/取消/异常/派发失败四分支语义化返回（照抄 3321-3390 既有模式）；连续拒绝计数（verify-progress 目录 directive 文件存在性+计数），≥2 次仍拒 → blocked + admin 升级告警（error 带两轮违规摘要）
- [ ] 2.3 重合成返回后回灌：`load_report → validate_report → 归因分级门 + 查重门` 全链复跑（同方法既有路径，不旁路）；合规走 `_clear_verdict_violations` + 状态映射重写既有推进
- [ ] 2.4 两处「拒绝落盘」日志文案改「拒绝采纳（report.json 已在盘上）」；「judge 下轮修文后自然通过」注释改写为 D1 真实回路描述
- [ ] 2.5 单测（tests/test_verdict_dedup_resynthesis.py 新建）：拒绝→落盘 violations+directive、重合成成功→回灌采纳、重合成再拒→blocked+告警、frozen 让位零写入、派发异常不复读旧 report（dispatch_exception 早退语义保持）

## 3. 重合成 prompt 注入与 judge 契约（core/agent_runner/prompt_builder.py + agents/planner-judge.md）

- [ ] 3.1 `_verdict_rejection_section` 兼容查重违规形态（scenario_ids 列表条目）：定向纪律扩展为「只重写清单内场景的 first_failed_step 与断言 triage evidence、其余字段原样保留、禁止复现/调查/改判定」
- [ ] 3.2 新增重合成指令段读取（dedup_resynthesis_directive.json 存在时注入）：被拒场景清单 + 逐场景差异化素材 + 「归因文本 MUST 引用本场景局部数据（步骤序号/断言 label/完整 error）、MUST NOT 套用共享模板串」契约
- [ ] 3.3 agents/planner-judge.md 增加归因文本契约段（≤10 行）：共享根因合法、归因文本逐场景可区分、禁截断同文；确认 worktree 部署路径（agent-config 部署在主树与 .fenix/ 两处，两处同步）
- [ ] 3.4 单测：directive 注入段渲染（有/无文件两态）、rejection 段对查重条目的清单渲染、judge 模板含契约段

## 4. in-place retry 派发前状态复查（core/agent_runner/runner.py）

- [ ] 4.1 扩展 `_should_give_up_before_retry`（或同款 helper）：增加 status 预期态判定（judge→testing、implementer→implementing，agent_type 映射表）；frozen/cancelled_hold 判定保持；fail-open 语义保持
- [ ] 4.2 两处原地重试通道接线：provider-transient（~2262 sleep 后 continue 前）与 artifact-gate（~2140 同位）在重派前调用 4.1 判定，命中放弃 → 返回语义化失败（error 标注「spec 已被接管，重试让位」）+ transient_retry 事件不写
- [ ] 4.3 单测：admin 置 blocked 后重试让位（无新 run 派发）、testing 态正常重试不回退、frozen 让位（既有语义）、checker 异常 fail-open

## 5. 集成验证与收尾

- [ ] 5.1 tests/test_verdict_dedup_resynthesis.py 集成链路：模拟 16:39 事故形态（5 场景共享根因模板归因）→ 拒绝 → 重合成差异化 → 采纳推进；模拟 15:53 形态（23 连真偷懒）→ 拒绝 → 重合成仍同文 → blocked 升级
- [ ] 5.2 全量相关测试：`python3 -m pytest tests/test_verdict_credibility_gate.py tests/test_incident_replay_credibility.py tests/test_verdict_dedup_resynthesis.py tests/test_verdict_retry_misattribution.py tests/test_judge_artifact_gate.py -x -q` 全绿
- [ ] 5.3 daemon 重启后 fenix-server 项目实盘观察一轮（若有 judge 拒绝场景则验证回路真实触发；无则留档等待自然验证）
