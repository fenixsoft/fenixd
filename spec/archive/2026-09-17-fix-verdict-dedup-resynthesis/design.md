## Context

2026-09-10 add-web-ui 四轮 judge $22.24 零采纳的事故解剖（详见 proposal）暴露三个耦合缺陷：

1. **查重门无出口**：`check_batch_attribution_dedup`（`core/verdict_check.py:618`）拒绝后，`_verify_verdict_evidence` 的 `batch_attribution_dedup` 分支只写 error 保持 testing 就 return——不写 `verdict_violations.json`（重试 prompt 注入通道 `prompt_builder._verdict_rejection_section` 因此收不到）、不 requeue judge、不升级。代码注释声称「judge 下轮修文后自然通过」，但该回路不存在。后果：spec 卡 testing 170 分钟撞 stuck 阈值触发全量重跑（$11 级 + 35 分钟墙钟），而重合成所需数据（report.json 完整在盘）免费可用。
2. **归一化指纹过粗**：`_normalize_attribution` 只拼 `cls + first_failed_step + assertion_triage 三元组`。judge 用脚本批量生成归因时 `error[:120]` 截断 + 共享模板串使 5 个级联场景完全坍缩——但这 5 个场景失败在同一前置步骤（单根因级联失败），归因高度相似本是合法形态，门的设计假设（逐字相同=偷懒）对它失配。
3. **in-place retry 不看 spec 状态**：`runner.py` 原地重试子循环（provider-transient 通道 2262 行附近、artifact-gate 通道 2140 行附近）在 sleep(backoff) 后 `continue` 重派，期间 spec 状态可能已被 admin/人工改为 blocked/frozen——19:48 轮 $4.77 白烧的直接原因。attempt 层已有 `_should_give_up_before_retry`（锁活跃 + frozen 判定）先例，但子循环层无对应检查。

约束：查重门本身行为正确必须保留（15:53 轮 23 连模板是真偷懒，拦对了）；重试 prompt 已有成熟的定向重试纪律注入（`_verdict_rejection_section` 的「只修清单内场景」），重合成回路必须复用同一通道避免双通道漂移。

## Goals / Non-Goals

**Goals**

- 拒绝→重合成→回灌→（必要时升级）的闭环，消灭 testing 自锁与全量重跑罚金
- 重合成 run 极轻量：只读既有 report.json + 重写被拒场景归因字段，无复现/无调查/无 worktree 深度作业，目标 ≤$0.5
- 归因契约前移进 judge prompt，让查重要求在产出前可见（事前预防优于事后拒绝）
- 归一化细分使单根因级联失败（真共享根因、场景局部证据各异）不再坍缩为同文
- 原地重试不与人工接管竞跑

**Non-Goals**

- 不改查重门拦截语义（≥3 阈值、拒绝即不采纳状态机推进，均保持）
- 不做 per-scenario checkpoint/增量落盘产物契约改造（烧钱大头在调查取证不在写盘；report.json 已整体落盘，重合成修字段即可）
- 不做裁决报告 schema 大改（级联豁免用归一化指纹实现，不新增 report 字段）
- 不动 verified 洗白门禁、缓存归因打标等既有治理（与本次正交）

## Decisions

### D1 重合成走「轻量 judge 重试」而非新 agent 类型

拒绝分支调用既有 `run_planner(spec_name, "judge")`（与 `violations` 二次违规重试同款），轻量性靠三件事保证：
- 落盘 violations（复用 `_write_verdict_violations`，违规条目带 `scenario_ids` 列表与重合成指令 reason）→ `_verdict_rejection_section` 自动注入定向纪律「只重写清单内场景的归因字段、其余原样保留、禁止复现/调查/改判定」
- prompt 注入段新增「重合成模式」形态：读 `dedup_resynthesis_directive.json`（拒绝时由框架写入，含被拒场景清单 + 逐场景现有归因文本 + 契约要求），judge 只需改写文本字段
- 复用 judge 通道意味着 frozen 门/取消旗标/stale-result 防护/产物硬门全部免费继承（`run_planner` 返回值已带这些语义化分支）

**否决的替代**：新 agent 类型（dispute-judge 式只读单轮）——隔离更好但要在 `_RUN_PREFIXES`、admin_monitor、run_files、dispatch 四处同源扩展，且丢掉既有重试通道的全部防御语义；收益不抵复杂度。

### D2 回灌与升级：重合成后同一入口再过全链校验，连续 2 次拒绝升级 admin

重合成 run 返回后走 `load_report → validate_report → dedup` 全链（同一方法内的既有代码路径，非旁路）；第二次仍 `batch_attribution_dedup` → 写 blocked（error 带两轮违规摘要）+ `escalation` 告警。拒绝计数用现有 `_retry_count` 或独立计数器均可，设计取独立轻量计数（落在 verify-progress 目录的 directive 文件 mtime 序列，避免 STATE.md 字段膨胀）——实现时若发现现有字段语义可用则优先复用。

**否决的替代**：无限重试（judge 换模型后可能自愈）——$0.5 级×N 仍劣于升级；且 15:53→16:39 实证了「换轮重跑」不会自然修正（重试轮反而产出了更差的 23 连相同）。

### D3 归一化细分：场景局部数据入指纹 + 级联根因前缀豁免

`_normalize_attribution` 扩展：
- `first_failed_step` 拆分「步骤序号/步骤动作」前缀与描述体——描述体再哈希取前 N 字符；步骤序号进指纹
- 断言 triage 的 `assertion` 字段（type+selector）本就逐场景不同，现实现已纳入——保留
- 级联豁免：当被比对场景组的 `classification` 相同、且描述体共享同一根因短语（归一化后 ≥80% 前缀重合），但各自失败步骤序号/断言清单不同 → 不计入查重（合法级联形态）

**否决的替代**：report schema 加 `cascade_root_cause` 声明字段让 judge 显式申报——语义最干净但要求 judge 配合新字段（prompt 漂移风险）、且存量门/测试全要改；指纹级细分零 schema 变更。

### D4 in-place retry 重派前状态复查

两处原地重试通道（provider-transient / artifact-gate）在 `time.sleep(backoff)` 后、`continue` 前增加检查：spec 当前 status 非「本 agent 预期态」（judge=testing；implementer=implementing）或 frozen/cancelled_hold → 放弃重试，返回语义化失败（复用 `_should_give_up_before_retry` 的模式扩展 status 判定，helper 就地扩展不新开方法名）。检查自身异常 fail-open（返回 False，保持既有重试语义）——与既有 helper 同约定。

### D5 「拒绝落盘」文案与注释修正随本 SPEC 顺手落地

日志「拒绝落盘」→「拒绝采纳（report.json 已在盘上）」；`verification.py` 「judge 下轮修文后自然通过」注释改写为描述 D1 真实回路。纯文案，随对应代码改动同 commit。

## Risks / Trade-offs

- [重合成 judge 仍产出同文] → D2 二次拒绝升级兜底；且 directive 文件附上「每个场景的失败步骤序号与断言 label 各不相同，归因文本 MUST 引用本场景局部数据」的机械化提示（数据框架已掌握，注入成本为零）
- [归一化细分放走新型偷懒] → 级联豁免要求步骤序号/断言清单逐场景不同——纯模板偷懒（连步骤引用都复制）仍会被拦；单测覆盖「共享根因+各异步骤」放行与「共享根因+同步骤」仍拒两侧
- [重合成与 auto-recovery 竞态] → 重合成期间 spec 保持 testing（现状语义），recovery 的 160min 阈值远大于重合成时长（分钟级）；stale-result 防护兜底
- [judge prompt 加契约段膨胀 prompt] → 契约段 ≤10 行，摊薄在 judge 已有 130+ 行模板内；输出 token 不增（归因字段本就要写）
- [状态复查在 checker 异常时退回现状] → fail-open 有白烧残窗口，但 admin SIGKILL 后 30s 内改状态的场景极窄；正确性与重试可用性取平衡点在 fail-open

## Migration Plan

纯框架侧改动，无数据迁移。部署后对存量 spec 无需处理（无持久化 schema 变更）。回滚 = revert 对应 commit，无残留状态。daemon 重启生效（老规矩：合并后必须重启）。

## Open Questions

（无——方向已与用户对齐：四项修复全做，按 D1-D5 落地。）
