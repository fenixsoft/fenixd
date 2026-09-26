## Deliverables

```yaml
- path: docs/help/04-cli.md
  kind: modify
- path: docs/help/05-verification.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
- path: docs/help/07-safeguards.md
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/10-artifacts.md
  kind: modify
- path: docs/help/11-logs.md
  kind: modify
- path: docs/help/12-faq.md
  kind: modify
```

## 1. 验证体系章补齐（docs/help/05-verification.md）

- [ ] 1.1 新增「env 豁免与 admin 握手」小节（verdict 四分类之后）：两级防线判据、共享计数 `_inconclusive_attempts`、`verify_engine.inconclusive_max_attempts`=3 / `inconclusive_escalate_attempts`=4、admin DISPOSITION 放行守卫（放行晚于本轮 SIGNAL 才有效）、`admin_disposition_backlink` 回链、「verified 卡在 implemented 反复重验」现象的排查指引；锚点 escalation.py 实读核对
- [ ] 1.2 新增「fastlane 小缺陷轻量通道」小节：三条件、code-fix 主树直接修复+子集重验（失败 ∪ depends_on 链 ∪ 下游链）、连续 2 次失败回落整轮、`fastlane_decision.json` 判定记录；锚点 fastlane.py 实读核对
- [ ] 1.3 新增「judge 门禁治理」段落：轮内 ≤2 停派+judge_rerun_cap 升级、spec 级 5 次硬上限 blocked、verdict 缓存裁剪修复轮重验范围；锚点 judge_gate.py/verdict_evidence.py 核对
- [ ] 1.4 伪失败防线表补两行：迟到 verifier 结果终态丢弃（legacy.py `_discard_if_not_testing` + verified 收敛回收在飞 verify 车道）；逐测超时门（pytest 10s signal + tests/timeout-allowlist.yaml 豁免登记）
- [ ] 1.5 新增「infra 失败预算豁免」段落：infra 轮不计入 MAX_VERIFY_FAIL_ROUNDS、run 预算退款幂等、三个 STATE 观测字段；锚点 state_machine.py:247-260 核对
- [ ] 1.6 并行出题补一段产物说明：parallel_plan.json 状态机与失败半成品隔离（engine.py:853-877 核对）；不与姊妹 SPEC 改写的流水线句子冲突（只增不改）

## 2. 治理规则章补齐（docs/help/06-governance.md）

- [ ] 2.1 瞬断治理节新增「解封渐进恢复」小节：态序（冻结>hold>探针观察窗>错峰放行>open）、`agents.transient_unseal_*` 五键键表（实读 config.py 核对缺省值）、「ready 却迟迟不派发」排查入口（unseal hold 日志特征）
- [ ] 2.2 新增「run 止损」小节：三件套语义 + `agents.run_stall_budget_enabled/_stalls/_window_minutes` 键表（缺省关闭）+ 与超时活性监督的关系（判停开启后停滞 run 终止而非无限续期）
- [ ] 2.3 新增「信号死法冷却」段落：连续 3 次信号死（Exit 143/负信号）→ 600s 冷却、全类型重派跳过不耗预算、到期自动恢复（provider_circuit.py:131-142 核对）
- [ ] 2.4 新增「SPEC 并发在飞守卫」段落（merge 修复通道节附近）：评审收尾不打回实现中 spec（`_review_skipped_result` 侧车）、实现派发前在飞评审探测、实现合并收尾补记转移
- [ ] 2.5 infra 豁免在「三类预算」表附近补一句交叉引用（详表在 05 章）

## 3. 保障机制章补齐（docs/help/07-safeguards.md）

- [ ] 3.1 新增「取消保持态」小节（冻结小节之后）：`_cancelled_hold` 有意等待语义（恢复链路跳过、唯一出路显式复位）、与 `_frozen_hold` 的并列互斥关系（冻结终止先清取消保持）
- [ ] 3.2 新增「stash pop 冲突三分诊」细节段（autostash 段展开）：三态处置链与 stash 条目保留记账（stash_guard.py 核对）
- [ ] 3.3 新增「merge-back spec 目录在飞守卫」段落：有界顺延（缺省 30 分钟/3 轮、`_merge_retry_pending`）、超限回落人工通道不耗预算
- [ ] 3.4 交付物守卫段补「relocation writeback 同层修正」：judge 修正写生效命中层（worktree/主树/dispute 核销三分支）、修正后按守卫读取基准复检、同族复发熔断
- [ ] 3.5 告警系统段补「信号前置探测与处置回写」+「告警降噪治理」：请求型信号已满足即 handled、daemon_errors 指纹冷却与孪生合并、fixture 项目抑制、spec_delivered_no_content 不冻结
- [ ] 3.6 陈旧自愈段补「悬空超时」：`max_dangling_seconds` 缺省 14400s（0=关）、超时走规划性重启、`stale_code_dangling_timeout` 告警

## 4. Dashboard 章校准与补齐（docs/help/08-dashboard.md）

- [ ] 4.1 分面 label 逐字校准（实读 list.tsx）：「SPEC 开发」→「功能开发」、「Claude Code 会话」→「会话接入」，全篇统一
- [ ] 4.2 SPEC 详情页结构分层重写：文档弹窗 5 页签与页面级 5 页签（运行时间轴/场景结果/Bug 列表/失败截图/Hook）分层枚举，消除「五个页签又冒出 Hook」的自相矛盾；实读 detail.tsx 核对页签集合
- [ ] 4.3 新增「会话接入」分面小节：显式开始/SSE 流/composer（`/` 命令与 skill 补全、`@` 文件提及、草稿持久化、Enter/Shift+Enter）/停止会话/空闲 1800s 回收/truncated 提示/移动端键盘适配/两个补全数据源端点（files 上限 5000、commands 缓存语义）
- [ ] 4.4 新增「质量门禁 Card」段落：6 道门清单与六态、done=passed+skipped、列表页 gates 橙色阶段两窗口、终态豁免行为（pushed 后 full-suite→skipped、ocr 门 merge-base 豁免）、「卡在哪道门」排查指引
- [ ] 4.5 新增「运行记录可读性」段落：心跳静默、语义系统条（provider_marker/transient_retry）、工具聚合、thinking 折叠与开关、向前分页
- [ ] 4.6 SPEC 列表补一句筛选 URL sticky（刷新/分享/前进后退保留；白名单 fail-safe）
- [ ] 4.7 测试回归分面补「自动修复回归问题」按钮（受理后回链轮询、指引到 CodeFixProgressCard）；代码审查分面补五动作按钮（全库审查/当期审查/自动修复/生成修复 SPEC/全部忽略）与触发受理回链三态（started/dropped/failed、ack_pending 409）
- [ ] 4.8 设置页描述校准（实读 settings/index.tsx）：页签全集（用户级 11 个 + 项目级追加 3 个）、「质量」页签 2 张 Card + ocr 探测 Alert 的现状描述
- [ ] 4.9 详情行工具条补「恢复运行」动作（取消保持态 SPEC 的一键恢复，含保留分支续做语义）

## 5. 配置参考章补录（docs/help/09-config.md）

- [ ] 5.1 agents 段新增 `agents.timeout_overrides.*` 键表与小节：键集（KNOWN_AGENT_TYPES 全集 + repair + supervision-judge）、≥300s 下限、supervision-judge ≥1s 特例（只管 liveness judge 子进程、不参与 absolute_max 派生）、覆盖优先于全局 run_timeout_seconds、影响 absolute_max 派生；实读 config.py:130-165,2218-2292 核对
- [ ] 5.2 agents 段补 `impl_run_budget_max`（缺省 100、硬天花板实读核对）与 per-spec 覆盖字段 `impl_run_budget_override` 说明
- [ ] 5.3 agents 段补 `agents.verify_redo_budget`（缺省 3）：仅 daemon 重启 testing 恢复路径计数、超限 verify_redo_exhausted 冻结
- [ ] 5.4 agents 段补 `agents.run_stall_budget_*` 三键（缺省关闭）；瞬断治理节补 `transient_unseal_*` 五键
- [ ] 5.5 stale_code_selfheal 段补 `max_dangling_seconds`（缺省 14400，0=关）
- [ ] 5.6 admin.code_review 段键表补 `scope`（window/full，恰为 full 才走全仓）与 `stall_alert_minutes`（缺省 15，零进度停滞告警）；「审查窗口与自省同源」表述限定 window 档
- [ ] 5.7 补 `admin.review_stall_minutes`（缺省 30，产物 mtime+CPU 双判据看门狗，与 codefix-review-lane-decoupling.md 交叉引用）与 `admin.mergeback_wip_orphan_grace_minutes`（缺省 30）两行
- [ ] 5.8 verify 段补 `repo_code_review_concurrency`（缺省 4）、`impl_code_review_mode`（gate/advisory，缺省 gate）、`impl_code_review_lane_timeout_sec`（缺省 2400）三键；均实读 config.py 核对缺省
- [ ] 5.9 admin.code_review_fix 节补缺失机制段落：WIP defer 台账双门、占用者协调、选批 WIP 预检、批失败自愈 fail_count 预算、salvage、批内并行 ≤4、LLM 拒绝出口、手动触发整链授权（code_fix_request.json + manual_authorized）、回归一键转台账（regression- 前缀/超时锚定 verify.yaml/复发重开）；条级进度与 startup_stage 在 08 章进度卡处描述
- [ ] 5.10 「Dashboard 设置页与配置键映射」表同步本轮全部新键的页签归属（实读 QualityPanel.tsx 等控件落位核对）

## 6. 文件地图与日志章补全（docs/help/10-artifacts.md、11-logs.md）

- [ ] 6.1 10-artifacts.md STATE.md 字段清单扩全：显式键补 start_after/frozen_until/impl_run_budget_override；新增「内部字段（`_` 前缀，无条件透传持久化）」小表，收录关键可观测字段（_verify_redo_count/_verify_fail_rounds/_frozen_hold/_cancelled_hold/_env_block_rounds/_infra_failure_count/_verify_infra_rounds/_infra_refunded_run_ids/_fastlane_fail_streak/_review_skipped_result/_recovery_resume/_repair_awaiting_remerge/_merge_retry_pending 等，实读 state_machine.py 序列化与常量区核对）并注明「完整集合以 state_machine.py 为准」
- [ ] 6.2 10-artifacts.md 目录树与「出问题去哪查」表补：verify-progress 下 parallel_plan.json/fastlane_decision.json/quality-gates.json；`.fenix/architecture/`；scheduling_kick/、spec_delete_request.json、code_fix_request.json、code_review_request_result.json、regression 的 .running、restart_history.jsonl、supervisor_fused、supervisor_runtime.json、code-review 的 fix-deferred.json/fix-progress.json/fix-failed.json/分片 out-<run_id>-b<N>.jsonl
- [ ] 6.3 11-logs.md code-review/ 工作区表补分片产物行与 fix-* 台账三件、code_review_request_result.json；「status（open/fixing/resolved…）」修正为 open/in_spec/resolved/ignored（fixing 是批 phase 非条目态）

## 7. CLI 与 FAQ 结构修复（docs/help/04-cli.md、12-faq.md）

- [ ] 7.1 04-cli.md：托管态三态表移除混入的三行脚本（fenix_archive.py/launch-chrome-extension.js/test_for.py 归位 bin/ 表）；bin/ 表补录 fenix_cli.py（promote/reflow/activate/review/unfreeze 子命令一句话）、fenix_status.py、fenix_verify_contract.py、ocr_review.py、run_full_suite.py（实读 bin/ 目录核对全集，写入用户可用的主要项）
- [ ] 7.2 12-faq.md：重复「## 9.」编号修正、后续条目顺延；「烧钱快」处置补 run 止损指引（`agents.run_stall_budget_*`）；第 1 条根因列表按宽松优先级调度口径核对修订
- [ ] 7.3 两文件 grep 自检：faq 标题编号无重复；04-cli 托管态表仅三态行；相对链接有效
