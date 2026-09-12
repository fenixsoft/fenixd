
## 2026-09-13

### 浪费
- **import-shadow 三次超时空转**
  - 影响：同一 spec 的实现 run 三次 12600s 超时（每次 3.5h，合计 10.5h 空转），第三次已跑满 91 rounds 仍被 extension budget 2/2 耗尽即杀；另 a3 被 daemon 关闭打断。spec 从 09-12 09:51（本地）首跑折腾至 09-13 01:00 才成功合并，横跨约 15h，期间 token 消耗不可观测（usage unobserved 提示 real consumption likely non-zero）。
  - 证据：fenixd.log 05:22:04/08:52:15/14:58:19 三次 "Timeout after 12600s — extension budget exhausted (2/2)"，run_id 分别为 impl-fix-root-init-import-shadow-1789177903-a1/a2/1789212482-a1；14:58:19 上下文中 1789212482-a1 报 91 rounds, median 13.2s, p90 33.7s, max 153.9s, stalls>60s=4 (4%)；10:57Z a3 被 SIGTERM（Exit 143）。
  - 调查评估：已核实：三次超时 log 与 runs/ 目录 jsonl 末尾 error 行一致（Timeout after 12600s — extension budget exhausted (2/2)），a3 被 daemon 10:57:25Z 关闭连带杀（4866 行 Sent SIGTERM）。根因：fix-root-init-import-shadow 属 import 遮蔽修复，任务面较大，fast-track 单次 3.5h 硬限内无法完成，触发 extension 2/2 即杀；且 a1/a2 处于 run-latency 转录盲区（0 rounds 无 timestamp 样本），观测不到是真卡死还是慢功。与存量 SPEC 关系：fix-run-latency-toolresult-parser（fa298deb 09-12 14:03 merge）已修转录盲区；add-impl-wip-checkpoint 的 WIP 保全在本案生效——1789212482-a1 超时后 WIP collapse 保全、a2 仅 87s 即收尾成功（15:00Z merge），说明保全链有效但超时判定牺牲了 3.5h。结论：属已验证功能的触发成本，次生（时间+不可观测 token）浪费成立，残余在「超时前自动保全」与「规模预检」两处。
  - 建议：给 fast-track 长任务加规模预检（任务数/预估轮次超阈时自动降级 full 或预留更多 extension），并在 extension #2 用尽前自动触发一次 WIP checkpoint 保全，避免已完成的 91 轮工作全部随超时作废。

- **两轮 implementer 零提交白跑 $24**
  - 影响：两起 [terminal-no-commit] 拦截各消耗一整轮 try：fix-run-latency-toolresult-parser（$12.05，worktree 1 个未提交产物）与 add-stale-code-selfheal（$12.13，worktree 11 个未提交产物），均回退 ready + 退避后重新派发，合计约 $24 白跑并延迟两 spec 完成。
  - 证据：fenixd.log 3992/4445 行 'Agent run exception: [terminal-no-commit] 归因:未提交即收工'（03:25:54Z 与 07:04:28Z）；runs/impl-fix-run-latency-toolresult-parser-1789176437-a1 与 impl-add-stale-code-selfheal-1789194797-a1 的 total_cost_usd 分别为 12.052304 与 12.1257625；配套 WARNING 显示两 spec 均被 Rolled back implementing → ready。
  - 调查评估：已核实：两条 ERROR 与对应 run 成本从 runs/ jsonl 直接读到，目标 spec 与回退动作在 3994/4447 行 state_machine 更新中吻合。根因：implementer 在 fast-track 下终止时未提交产物（归因 '未提交即收工'），gate 拦截成功避免污染主树，但消耗了一轮 try 的 token。与存量 SPEC 关系：add-impl-terminal-nocommit-gate、add-impl-wip-checkpoint 正在飞（后者 verification-report 已生成），本案即该防线的触发记录，属 gate 生效后的预期内损耗；残余缺口在投射侧引导而非拦截侧。结论：单次约 $12 的重复 try 成本，复发敞口明确，建议从发生概率（implementer 收工提示）侧再削减。
  - 建议：在 implementer system prompt / 收工契约中强化「有产出必须 git commit」的强制步骤（如收工前 lint 清单包含提交检查），把 terminal-no-commit 从『拦截后重试』前移为『投射时预防』，降低每次 $12 级白跑概率。

### 失误
- **探针连死实例阻塞两 Spec 95min**
  - 影响：契约轻量自证/就绪探针持续 120s 超时 Connection refused，verify_env_blocked 死循环：fix-dashboard-fault-isolation 阻塞 96min、fix-supervisor-hosting-chain 阻塞 94min，期间触发 8 个 admin 处置 run、其中已记账成本 $13.76+$3.51=$17.27（另 2 个被 kill/取消未记账），blocked_stuck critical 告警 3 次；修复提交（a49c741e 10:00:49Z）到 daemon 重启生效存在约 57min 部署空窗。
  - 证据：admin_alerts.json：09-42:13Z / 09-44:14Z 两起 '就绪探针超时（120s）Connection refused'；10:05:21Z disposition 明确根因 'serving_registry 周期清扫收割轮间实例后，daemon 内存缓存 _contract_static_servers 仍持有已死实例，_current_instance_base_url 不检查 liveness'；11:19Z/11:32Z blocked_stuck '超过 96/94 分钟未处理'；a49c741e 提交说明（liveness 守卫 getattr(srv,'ok',True)）与 80aec3ed（探针换 /api/alerts）均 git show 核实；10:57:38Z disposition 'daemon 运行 pre-a49c741e 旧代码'，10:57:25Z daemon Shutting down planned=False 连带杀 impl-fix-root-init-import-shadow-a3、admin-1789207935、repair-1789209877 三个在跑 run（4866-4868 行）。
  - 调查评估：核实链完整：首警 09:42（UTC）→ 根因归位 10:05 → 修复提交 10:00:49Z / 探针换端点 11:28Z → daemon 10:57Z 重启后生效 → 两 spec 11:37Z 前后解除（supervisor 已 pushed、dashboard c4c6f555 19:53 本地 merge）。根因双层：① verify-serving 实例缓存不查 liveness，把已收割死实例 base_url 供给自证/探针；② 探针原用 /api/projects（冷启动 7.58s > probe_ready 3s，见 10:12Z disposition）。修复本身正确且当日闭环；失误点在部署链路——修复 10:00 提交、daemon 10:57 才重启，近 1h 空窗内探针持续失败且重启采用 planned=False fast 模式无 drain 保护，直接中断 3 个在跑 run（1 个修复 run 白跑、a3 中断、1 个 admin 被杀）。与存量：该缺陷是验证 harness 基础设施问题，由 fix-dashboard-fault-isolation 的验证环节暴露，非该 spec 本体；已修（a49c741e + 80aec3ed + 回归测试 test_current_instance_base_url_skips_harvested_server）。结论：当日最大事故，影响面两 spec 阻塞 ~1.6h + $17.27 admin 成本 + 3 run 中断，已闭环，残余在修复部署时效与重启保护。
  - 建议：a49c741e 类基础设施修复落地后自动触发 daemon 重启（或重启前对在跑 run 走 drain 而非 fast 杀），并排查 admin_alerts 处置记录里 'probe_ready 3s' 阈值是否仍会用慢端点误报；探针端点统一走 /api/alerts 后补一条验证自检确认无回归。

### 可改进
- **冻结场景 schema 失配验收卡壳**
  - 影响：复发敞口：冻结场景文件 test_scenarios.json 以旧 schema 生成（run 步骤 value→command、output_match 断言 value→expected 字段重命名未迁移），load_scenarios 抛异常判 corrupt → 验收失败且冻结场景不自动重出题，须 admin 裁决——单次代价 2 个 admin run $7.28 + 处置后 blocked_stuck 再卡 17min；另暴露『admin 修复后 spec 状态未复位』第二缺陷（非 env 阻塞族不触发自动复位）。
  - 证据：admin_alerts.json 15:00:04Z 升级告警 '冻结场景文件损坏或验收失败'；15:13:12Z disposition 'run 步骤 value→command，output_match 断言 value→expected，load_scenarios 抛异常返回 corrupt'；15:33:09Z disposition '第一次 Administrator 处置成功修复场景文件后未复位 spec 状态——blocked_stuck 非 env 阻塞族，框架不触发自动复位'；admin-fix-root-init-import-shadow-1789225205/1789226281 两 run 成本 4.0078615+3.273667；当前 .fenix/verify-progress/fix-root-init-import-shadow/test_scenarios.json 已是新 schema（step0 键 action/command）且留有 .bak-corrupt 备份。
  - 调查评估：已核实：schema 漂移事实、两 admin run 成本、当前文件已修复均可直接查看；场景冻结机制（跨轮一致不自动重出题）在本案按设计触发，但把 schema 演进缺口交给了人工。根因：冻结文件无 schema 版本标记，字段重命名（value→command）未做读侧迁移/容错，load_scenarios 直接抛异常；且处置后状态复位仅覆盖 env 阻塞族，blocked_stuck 需人工再触发。与存量 SPEC 关系：fix-frozen-scenario-orphan-reservoir 在飞，7aedb932（09-12 23:08 本地）已补『内容闸门冻结补结构化 frozen 标记』，方向一致但未覆盖 schema 版本迁移。结论：系统性缺口成立，可独立起草 SPEC，低成本修复（读侧兼容 + 版本标记）。
  - 建议：立项：冻结场景文件读侧加旧 schema 兼容迁移（value→command / output_match→expected）或写入时打 schema 版本并在 load 失败时报具体字段差异而非笼统 corrupt；admin 处置成功修复后统一复位 spec 状态，消除 blocked_stuck 二次空转。

- **fast-track 长任务缺规模预检**
  - 影响：复发敞口：单 spec 三次 12600s 超时合计 10.5h 空转，若加规模预检可在首个 run 前拦截（单次代价 3.5h run 时长 × 3 + 不可观测 token 消耗）；add-verify-preflight-gate 已覆盖入口存在性预检，但未覆盖任务规模维度。
  - 证据：fenixd.log 4163/4733/5278-5279 三次 fast-track Timeout after 12600s（run impl-fix-root-init-import-shadow-1789177903-a1/a2/1789212482-a1），其中第三次已 91 rounds 才被杀；对照同窗口内较小 spec（fix-dispatch-wakeup-gap 1789214098 等）均单轮成功，规模差异显著。
  - 调查评估：已核实：三次超时均为同一 spec 且最后一次已完成 91 轮工作，说明是『硬限内跑不完』而非卡死；对照组小 spec 单轮成功，规模相关性明显。根因：fast-track 模式按统一 3.5h/6 次预算派发，无任务规模预估，大 spec 被同规格对待。与存量 SPEC 关系：add-verify-preflight-gate 的 resolve_entry_path 预检（09-11 merge）解决入口存在性；add-turn-limit-anchor-c 解决轮数锚点；均未覆盖『任务规模 → 预算档位』映射。结论：可独立成 SPEC 或并入 preflight 扩展，价值点是用一次轻量静态预估（tasks.md 条目数/变更面）换掉 3×3.5h 空转。
  - 建议：起草 SPEC：fast-track 派发前按 tasks.md 任务数、预估轮次做规模分档，超阈自动降级 full 模式或提高 extension 预算；并在 extension #2 用尽前触发自动 checkpoint 保全已完成的轮次工作。
