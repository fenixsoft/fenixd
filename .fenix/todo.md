## 2026-10-13

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 14 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

### dsh 真实全链验收执行请求（dsh-primary-acceptance-switch，人工队列）
- **请求**：执行 dsh 通道真实全链验收（真实模型调用，属人工运维门控动作，agent 仅完成预演与登记，实际执行由用户发起——参照 restart_request 信号范式）

- **执行命令**：`python3 bin/dsh_acceptance.py accept --go`（先跑 `python3 bin/dsh_acceptance.py accept` 预演确认自检全绿）

- **前置条件**：① dsh 在 PATH 且版本在白名单（`0.2.0-rc.2`）；② Bundle 已挂载（`dsh --profile fenix --dump-config` 可见 headless-runner 段，详见 dsh-bundle/README.md 安装段）；③ `llm.providers` 至少一项 baseurl+apikey 齐备；④ claude CLI 在 PATH（基线车道；可 `--no-claude-baseline` 跳过）；⑤ 避开已知 429/断供窗口（每日 04:30 前后）

- **预计耗时**：4 车道（claude 基线 implementer + dsh implementer/verifier/judge）× 单车道 900s 上限，实测通常 10 分钟内

- **产物**：`.fenix/verify-evidence/dsh-primary-acceptance-switch/dsh-acceptance-real-*`（五段证据报告 + 决策申请段）；报告模板见 docs/help/dsh-harness-runbook.md 第五节

- **agent 预演记录**：2026-10-13 accept 预演自检全绿（5/5 项：dsh 可用 / provider 链凭据 7 个 / dsh 健康门通过 / claude CLI 命中 / 临时夹具可写），dry-run 计划输出正常，全程零真实模型调用

- **裁决提醒**：验收报告第六节「默认值翻转 claude→dsh」为用户裁决项，翻转属后续一次性微变更，不在自动化链路


## 2026-10-14

### 浪费
- **蒸馏重试台账未提交滞留全天，阻塞 merge-back 9 分钟并耗一次 admin run**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：dsh-primary-acceptance-switch 的 merge-back（实现分支合回主树）被 WIP 重叠闸门阻塞 22:54:45→23:03 共约 9 分钟，6 次×2 分钟自动重试全败，消耗 1 次 admin 车道 run（admin-dsh-primary-acceptance-switch-1791903542，只读诊断+代提交）并产生 6 条 ERROR 日志；复发敞口：蒸馏失败登记或任一无提交写路径写入 todo.md 后，再有任一 spec 分支（普遍追加 todo.md 节）合回即复现，单次代价约 9 分钟合回延迟加 1 次 admin run。
  - 证据：日志 6 条「Merge-back blocked by WIP overlap precheck」（2026-10-13T14:54:45Z→15:01:15Z，约 2 分钟一拍）；处置记录 7ba19ebca803（mergeback_wip_overlap 处置）诊断「主树唯一重叠改动为 .fenix/todo.md 头部一行 knowledge-distill 重试待办」；commit 517c92e1（23:01:27，仅 .fenix/todo.md 1 行）解除阻塞，合并提交 eef7f622（23:03）落主树。
  - 调查评估：问题源：dsh-primary-acceptance-switch 合回时暴露。已核实：阻塞行与 core/knowledge.py:629 蒸馏失败重试登记文本逐字吻合，该路径经 append_todo_line（knowledge_backfill.py:188，向 todo.md 追加行的共享写函数）写入且全程无 git 提交，行自 10-13 00:14 自省窗口开启时已在册、滞留至 23:01 代提交；合并 admin 诊断确认两侧改动位置不重叠（主树头部插行 vs 分支尾部追节），闸门按路径重叠保守拦截属正确行为。根因：系统性缺口——ADR-060 已确立「todo.md 类产物写入点即时 commit」原则，刚归档的 spec 2026-10-12-evo-add-todo-marker-commit-on-write 只覆盖了 write_todo_marker（自进化标记）路径，其非目标段明确把 knowledge_backfill.append_todo_line 等写路径排除（「可另行评估立项」），本次事件即该延期的成本兑现。与存量工作关系：与归档 spec 互补而非重复，是其一非目标的直接立项依据。结论：值一个独立微 SPEC，封住剩余无提交写路径。
  - 建议：立项扩展 commit-on-write 至 append_todo_line 全部调用方（core/knowledge.py:780/1440 与蒸馏重试登记等），复用 core/self_review.py _commit_todo 的就地提交与同轮合并提交形态；最低成本方案是先给 knowledge.py 蒸馏重试登记单点加就地提交。

### 失误
- **AGENTS.md 交付物误用软链载体，交付物守卫判缺件打回一轮返工**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：add-fenix-dsh-bundle 实现 run 因交付物守卫（落地产物核验闸门）判 AGENTS.md missing 而被挡，追加 1 轮原地修复（两个 commit）与复验，该 run 成本 22.23 美元（implementer 车道中位 5.40 美元的 4.1 倍），spec 合回被推至 17:40 才完成。
  - 证据：日志 2026-10-13T07:54:41Z [pm_engine]「交付物守卫触发 'add-fenix-dsh-bundle'（缺件 AGENTS.md（missing））」run=impl-add-fenix-dsh-bundle-1791871868-a1；修复 commit 1a7e1bf2（16:10「AGENTS.md 软链(120000)改同内容实体文件(100644)」）+ 4bffac0b（16:15 sha256 全等复核）；run_metrics cost_usd=22.23115。
  - 调查评估：问题源：add-fenix-dsh-bundle 实现收尾时暴露。已核实：git 中软链是 mode 120000 的特殊对象而非实体 blob，守卫按实体文件核验故判 missing——守卫行为正确，失误在实现侧交付物载体选型（SPEC/tasks 未写明载体形态要求，实现者默认选了软链）。当轮已完成修复与逐字节复核，属当轮闭环的执行失误、无残留。与存量工作关系：spec 内一次返工，无需新 SPEC 治理单点；残余敞口是「交付物载体形态」在 SPEC 模板与实现车道提示词中均无约定，同类选型歧义可在其他 spec 复现。结论：低频失误，一句模板约定即可消除。
  - 建议：在 SPEC 模板交付物清单或实现车道提示词中补一句「交付物须实体文件（git mode 100644），禁止软链（120000）载体」，消除载体选型歧义。

### 可改进
- **daemon 旧代码悬空 8 小时触顶强制重启，空闲自愈被连轴 run 饿死**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：当日三批合回的框架修复（add-harness-adapter-layer 13:57、add-fenix-dsh-bundle 17:40、add-dsh-adapter-integration 21:33）延迟到 21:58:58 规划性重启才装载，悬空整 8 小时（28800 秒恰达 max_dangling_seconds 上限）；本次零实害（窗口内 0 失败 run），复发敞口是悬空期内全部车道按旧代码执行——在飞 SPEC 提案已记载 10-11 同根实害两起（收尾双提交 5 对、蒸馏产物滞留 21 小时）。
  - 证据：告警 7185ed947ac9（stale_code info 级首见，13:58 本地）→ 告警 b43d2021c459（stale_code_dangling_timeout 升级，21:58，原文「悬空 28800s > 时限 28800s」，动作 touch .fenix/restart_request）；进程核验：fenixd daemon 新进程 21:58:58 启动，升级后 57 秒内重启落地；归档告警显示同类升级历史上已 5 次（9-26～9-30），本次为第 6 次。
  - 调查评估：问题源：当日 42 个 run 连续执行、无 600 秒连续空闲窗（stale_code_selfheal.idle_confirm_seconds 缺省值），空闲确认型自愈全天饥饿，只能等 8 小时时限强转——机制链按设计工作（升级→restart_request→supervisor 秒级重启），但装载延迟未被缩短。已核实根因归属：非一次性失误，是「空闲确认」前提在高压日的结构性失效。与存量工作关系：在飞 spec evo-add-key-path-stale-code-preflight 正是此根因（提案引三周 70 次检测→装载配对中 12 次 ≥2 小时、最长 22.05 小时），本次是其问题陈述的新实例、且首次以满 8 小时时限触发的形态出现；升级告警滞留未处理（handled=False）由另一在飞 spec add-alert-self-heal-marking 的安静窗自愈闭环覆盖。结论：不重复立项，两在飞 SPEC 均应优先落地。
  - 建议：优先安排 evo-add-key-path-stale-code-preflight 验证合回，让关键路径（收尾提交/蒸馏派发/admin 处置）预检→restart_request 的分钟级装载通道投产；若短期无法落地，可评估下调 max_dangling_seconds（如 4 小时）缩小敞口，代价是更频繁的规划性重启排水。

- **run 停滞遥测缺事件类型注记，33 次停滞无法区分工具执行与 API 等待**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：4 个离群 run 合计 33 次停滞（stall，事件流相邻事件间隔超阈值）、最长单次 298.7 秒，因遥测只记间隔时长不记边界事件类型，审查无法裁决是长工具调用（全量回归等合法耗时）还是 provider 往返/重试浪费，结论只能停在形态层、根因未定。
  - 证据：数据摘要第六节深扫：impl-add-dsh-adapter-integration-1791884537-a1 stall=11 max_gap=262.6s；impl-add-fenix-dsh-bundle-1791871868-a1 stall=11 max_gap=298.7s；impl-add-harness-adapter-layer-1791863204-a1 stall=6 max_gap=199.7s；planner-judge-add-dsh-adapter-integration-1791894482-a1 stall=5 max_gap=288.0s（已核实其档案 244 事件、62 次 Bash 调用，20:28–21:03 本地为命令密集型评审，非空转）。
  - 调查评估：问题源：三个大型 spec 实现 run 与一个出题评审 run 的离群初筛暴露。已核实：全部停滞无中途 stderr、四个 run 均成功收尾；planner-judge 档案显示 Bash 密集型工作，推测大间隔多为长命令执行，但 impl 三个 run 无事件级证据可在两假说间裁决——按归因边界规则只写形态层、不预设根因。与存量工作关系：evo-add-run-metrics-lane-baseline 已建车道基线使离群可初筛，本缺口是停滞维度的遥测表达能力，属互补不重复。结论：小改动即可让每日自省从「形态层」升到「归因层」，避免每轮审查重复人工翻档案。
  - 建议：run 事件流落盘时为停滞区间标注边界事件类型（工具执行 vs API 往返），self-review 聚合按两类分列透出计数与最长间隔，使离群审查可直接区分合法长工具与等待浪费。
