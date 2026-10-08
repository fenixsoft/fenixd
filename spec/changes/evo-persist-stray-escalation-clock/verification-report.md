# 验证报告：evo-persist-stray-escalation-clock

> ⚠️ 本报告由框架于 2026-10-08T19:12:53Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T19:11:04.617810+00:00+run-result@mtime1791486759013920516

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 11/12 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

12 场景：11 通过，1 产品 Bug（major）。唯一失败 stray-clock-corrupt-state-fallback：注册表文件非法 UTF-8 字节损坏时 UnicodeDecodeError 未被捕获致主盘点崩溃（stray_wip.py:833），违反 tasks.md 1.1 fail-open「不阻断主盘点」的字节层容错要求；JSON 层容错在场、字节层缺失。其余重启计时连续/升级不重复/info 一次性去重/惰性清理/落位与 schema/既有套件回归/potplayer 接线与清债/升级信号消费链全部通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 2.13M |
| 本链增量 Token（输出） | 0.05M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code

- 关联场景：stray-clock-corrupt-state-fallback
- 描述：untracked 注册表持久化文件遭字节层损坏（非法 UTF-8）时，_load_untracked_registry 仅捕获 FileNotFoundError/OSError，UnicodeDecodeError（ValueError 子类）未被捕获并上穿 sweep()，主盘点整体崩溃退出 1——违反 tasks.md 1.1「文件损坏回退空表并留一条告警、不阻断主盘点」，该条明确要求损坏容错覆盖字节层（UnicodeDecodeError）与 JSON 层两类
- 根因：core/worktree_manager/stray_wip.py:832-842 异常处理缺 UnicodeDecodeError/ValueError 分支：read_text utf-8 解码失败在 :844 json.loads 之前即抛出逃逸；既有单测 test_corrupt_registry_file_falls_back_without_blocking 仅覆盖 JSON 层（合法 UTF-8 坏 JSON），字节层缺口由本场景暴露
- 证据（场景 stray-clock-corrupt-state-fallback 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "expected": 0, "actual": 1}, {"type": "output_match", "selector": "SCENE4_PASS", "expected": "损坏注册表回退空表、留降级告警、主盘点不阻断", "actual": "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 1 — 自 stray_wip.py:833 read_text 上穿 sweep():346，主盘点崩溃 exit 1"}]
  - screenshots: []
  - first_failed_step: 步骤2: 状态文件写坏为非法 UTF-8 字节后新实例盘点——UnicodeDecodeError 未被捕获，sweep 整体崩溃退出 1，未回退空表


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| stray-clock-restart-elapsed-continuous-escalate | 重启后滞留计时连续：6 个 untracked 散件（越阈值 5）建档落盘后，以全新 sweeper 实例模拟 daemon 重启（内存清零、盘点时载入持久化注册表）；向持久化条目注入 25 小时前合成 first_seen 再盘点，断言 maintree_untracked_stray_escalated 升级命中、status=escalated、elapsed_minutes≥1440（若重启清零计时则 elapsed≈0 升级永不命中）、同轮 info 一次性告警各 1 条。出处：spec.md Requirement 1 Scenario 1 + Requirement 4 Scenario 1；stray_wip.py:202（纯内存现状）、:55（24h 阈值）、:618（双档标记） | pass | 0/3 | - |
| stray-clock-escalated-marker-no-refire-restart | 已升级集合跨重启不重复升级：以可配体积阈值（maintree_untracked_stray_size_threshold_bytes=10 字节、散件 32 字节）驱动体积升级当轮命中，重启模拟（新实例）后再盘点——体积条件仍满足但 escalated_signal_at 标记随注册表恢复保持置位，major 升级信号不重复产生（库中仍 1 条、status 不再 escalated）。出处：spec.md Requirement 4 Scenario 2；tasks.md 1.2；stray_wip.py:618（双档标记门控）、:59（DEFAULT_UNTRACKED_ESCALATION_BYTES） | pass | 0/2 | - |
| stray-clock-info-alert-dedup-restart | 同指纹 info 一次性告警跨重启去重：grace=0（合法配置=耗尽即升级）使 maintree_untracked_stray_stale（info）首轮即发且 escalated_at 落盘，重启模拟（新实例）后同集合再盘点——不产生第二条 info 新告警（仍 1 条）、status 回落 timed 而非再次 alerted；体积不触 500MB 缺省阈值、无升级信号误发。出处：spec.md Requirement 2；tasks.md 1.2；stray_wip.py:47（UNTRACKED_SIGNAL_TYPE）、:607（escalated_at 一次性门控） | pass | 0/2 | - |
| stray-clock-corrupt-state-fallback | 持久化损坏降级（fail-open）：建档落盘后将状态文件写坏为无效 UTF-8 字节序列（半截写入/磁盘错误的典型损坏形态——不仅 JSON 语法错，读码层即非法），新实例盘点回退空表重新宽限（elapsed_minutes<30 证明 first_seen 重置）、留一条降级告警（logger warning 或 AdminStore 新增记录任一通道在场）、主盘点不阻断（返回含 untracked 子 dict）；状态文件缺失路径同样盘点不阻断（缺失属正常形态）。损坏容错须覆盖字节层（UnicodeDecodeError）与 JSON 层（ValueError/TypeError）两类。出处：spec.md Requirement 1 Scenario 2；tasks.md 1.1（文件缺失或损坏回退空表并留一条告警、不阻断主盘点） | failed（已修正） | 2/2 | product-bug |
| stray-clock-stale-path-lazy-cleanup | 失效路径惰性清理后不复燃：建档落盘后删除盘上全部散件，下一轮盘点集合为空（返回无 untracked 键形态）、持久化状态不再含任何指纹条目（空指纹整条删除）；重建同名散件后新实例盘点 first_seen 从零起算（elapsed_minutes<5 不继承历史时钟）、无任何告警复燃。出处：spec.md Requirement 3；design.md 风险条目（注册表与盘上实态漂移靠惰性清理每轮收敛） | pass | 0/3 | - |
| stray-clock-state-file-location-atomic-schema | 持久化落位与条目同构：建档落盘后状态文件位于项目 .fenix/ 运行时状态区（与 restart_history.jsonl 同区、被 .gitignore .fenix/* 吸收不产生散件噪声）、JSON 可解析、条目与现行内存条目同构（含 first_seen/first_seen_iso/files/escalated_at/escalated_signal_at——升级标记 MUST 随注册表持久化）且不含每轮现采的 sizes_bytes/total_bytes、files 与散件集合同构（6 项）；原子写以源码 os.replace 证据 + 落盘后无 .tmp/.part 等临时残留佐证，追加两轮盘点后状态文件仍持续可解析。出处：tasks.md 1.1；design.md 方案 1（落位/写时机/条目字段）；stray_wip.py:193-201（现行内存条目形态） | pass | 0/2 | - |
| stray-clock-d5-docstring-superseded | 模块 docstring D5 注记同步改写：core/worktree_manager/stray_wip.py 模块 docstring 的 D5 段不再维持「不引入新的持久化状态文件」旧决策原样在场——要么移除旧句、要么显式注明对 untracked 注册表被本 SPEC 持久化取代；tracked 流维持内存态的语义仍在场（内存态/内存字样）。出处：tasks.md 1.1 末句；stray_wip.py:22-23（D5 现状注记） | pass | 0/2 | - |
| stray-clock-existing-suite-regression | 既有测试套件回归 + 新覆盖在场：tests/test_verify_evidence_placement.py 全量通过（30 分钟宽限、5 条阈值、500MB 体积阈值、指纹规则、negation/ignore 豁免等既有语义不被持久化改造破坏），且文件新增本 SPEC 要求的覆盖用例（restart/persist/reload/corrupt/lazy/escalat 词表命中任一 test 函数名）。出处：tasks.md 1.1（阈值语义不变）+ 2.1；pytest 仅用 -v 不并列 -q（-q 抑制 PASSED 行致断言全灭） | pass | 0/3 | - |
| potplayer-verify-yaml-retention-wired | 项目侧接线（一次性运维）：/root/potplayer-base/.fenix/verify.yaml 显式声明 evidence_retention（dict 且含正整数 max_binary_bytes），YAML 语法合法可解析（safe_load 通过）。出处：tasks.md 3.1；core/verify_contract_template.yaml:155-156（声明语法参照）；stray_wip.py:121-144（已上线分级留存字段） | pass | 0/2 | - |
| potplayer-tasks-md-paths-rewritten | 活跃 spec tasks.md 落位路径改写：/root/potplayer-base 的 neutralize-pack-static-fingerprints 与 pack2-official-encoder 两个 tasks.md 中，所有 verify-evidence/ 引用均带 .fenix/ 前缀（裸根路径残留 0 处、改写形态≥7 处——tasks 3.2 点名的 7 处行号 10/12/169/199/56/58/65 已实测全部为改写后形态）。出处：tasks.md 3.2 | pass | 0/4 | - |
| potplayer-stray-debt-below-gates | 存量散件清债达标（一次性运维）：以框架 sweeper 同款只读口径（_untracked_stray_entries：porcelain -uall + check-ignore 豁免，零触碰）盘点 /root/potplayer-base 主树，真散件数低于 info 告警阈值 5、集合体积低于 500MB 升级阈值——存量 485MB/92 项散件经裁决执行器清债后不再构成任一告警/升级条件（实测余 1 个特殊字符名夹具 bin，33MB 级）。出处：tasks.md 3.3；stray_wip.py:63（DEFAULT_UNTRACKED_THRESHOLD）、:59（DEFAULT_UNTRACKED_ESCALATION_BYTES）、:449（只读口径） | pass | 0/3 | - |
| escalated-signal-consumable-by-adjudicator | 升级信号可被裁决执行器消费：临时仓以体积路径产生真实 maintree_untracked_stray_escalated 记录后——choices_for 注册含 archive/ignore/delete 三裁决选项；parse_stray_wip_manifest 从该记录 evidence「文件清单(N):」段回读清单与造的散件集一致（段级口径单源）；_exec_archive_untracked_stray 真实消费该信号完成归档移动（evidence_0.log 移入 .fenix/stray-archive/、error 为空）。出处：spec.md Requirement 4 AND 子句；core/dashboard/data/adjudication_choices.py:354-358、core/dashboard/data/admin_actions.py:2666（manifest 解析）/3229（归档执行器） | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。
