## Why

2026-09-10 fenix-server 项目 add-web-ui：四轮 planner-judge 共 $22.24 **采纳数为零**。批量归因查重门（add-verdict-credibility-gate D4）拦截了两轮模板化归因（正确），但 16:39 轮 $11.16/10.06M input 的高质量裁决（judge 实测复现、读源码、修 4 个场景文件）因 5 个单根因级联场景的 `first_failed_step` 套用同一模板串被误拒。更严重的系统性缺口：拒绝后框架「保持 testing 等重合成」但**不存在重合成回路**（不 requeue、不落盘违规清单、重试 prompt 收不到查重要求）→ spec 卡 testing 170 分钟自锁 → 撞 stuck 阈值触发全量重跑。另有一笔浪费：admin SIGKILL 在飞 judge 止损后，provider-transient 的 in-place retry 不复查 spec 状态（admin 已置 blocked），30s 后照派重试轮 $4.77 跑完被 stale-result 防护丢弃。

## What Changes

- **拒后廉价重合成回路（最高杠杆）**：`batch_attribution_dedup` 拒绝时落盘 violations（复用既有 `verdict_violations.json` 通道），派一个面向被拒场景的轻量重合成 judge run——只重写被拒场景的归因字段（`first_failed_step`/断言 triage evidence），不改判定、不复现、不调查；回灌同一道 dedup 门；连续 2 次重合成仍被拒 → 升级 admin 而非静默卡 testing。
- **judge prompt 归因契约**：`agents/planner-judge.md` 增加归因文本契约——根因/classification 允许共享，但 `first_failed_step` 与断言 triage evidence 必须引用本场景自己的步骤序号/断言 label/完整 error（禁模板串、禁 `error[:120]` 截断致多场景同文）；查重要求进入 judge 事前视野（现状只在拒绝后才知道）。
- **dedup 归一化细分（降误伤）**：`check_batch_attribution_dedup` 的归一化把场景局部数据纳入指纹——步骤序号、完整 error、断言 label；可选级联豁免：同一 `classification` + 同一 `first_failed_step` 根因前缀但失败步骤/断言各异的场景组不算命中（单根因级联失败的合法形态）。
- **in-place retry 派发前状态复查**：provider-transient / artifact-gate 两处原地重试通道，sleep 后重派前检查 spec 当前 status——已被人工接管（非 testing/实现中态）即放弃重试（复用 `_should_give_up_before_retry` 模式，扩 status 判定）。
- **两处误导修正**：日志「拒绝落盘」改「拒绝采纳」（report.json 实际在盘上，judge 自己写的）；`verification.py` 中「judge 下轮修文后自然通过」的注释描述的是不存在的回路，随本 SPEC 落地真实回路后改写。

## Capabilities

### New Capabilities

- `verdict-dedup-resynthesis`: 批量归因查重拒绝后的廉价重合成回路——违规清单落盘、定向重合成派发、回灌校验、二次拒绝升级 admin；以及 in-place retry 派发前 spec 状态复查。

### Modified Capabilities

（无——查重门本身与裁决证据契约的行为兼容，未改变既有 requirement 的对外语义；`add-verdict-credibility-gate` 已带 verification-report 属已完成历史 spec，不追加 delta。）

## Impact

- `core/verdict_check.py`：`check_batch_attribution_dedup` 归一化细分（新增级联豁免与场景局部指纹）。
- `core/pm_engine/verification.py`：`_verify_verdict_evidence` 的 `batch_attribution_dedup` 分支——落盘 violations + 派发重合成 run（新增方法）+ 回灌校验 + 二次拒绝升级；两处「拒绝落盘」日志文案。
- `core/agent_runner/runner.py`：`run_planner` 或 `_execute_agent` 路径支持 judge 重合成模式（轻量 prompt、无 worktree 复用 judge 通道即可）；原地重试子循环（provider-transient 与 artifact-gate 两通道）重派前状态复查。
- `core/agent_runner/prompt_builder.py`：重合成 prompt 段（定向场景清单 + 只改归因字段契约）；`_verdict_rejection_section` 增加查重违规形态支持。
- `agents/planner-judge.md`：归因文本契约段。
- 测试：`tests/test_verdict_credibility_gate.py`、`tests/test_incident_replay_credibility.py` 扩展 + 新增重合成回路集成测试。
- 成本模型：重合成 run 目标 ≤$0.5 级（只读 report.json + 改字段），替代 $11 级全量重跑与 170 分钟自锁。
