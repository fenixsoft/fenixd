<!-- knowledge: capability=daily-self-review rev=4 sources=spec/archive/2026-09-10-add-daily-self-review,spec/archive/2026-09-29-evo-alert-noise-governance,spec/archive/2026-10-12-evo-add-self-review-todo-fallback-honesty,spec/archive/2026-10-30-evo-self-review-evidence-bound-attribution -->

# 每日定时自省

daemon 每晚由 Administrator Agent 自动复盘当日运行（浪费/失误/可改进），结构化追加到项目 todo.md，为 SPEC 立项提供可追溯输入。

## 现行规则

- 定时执行：`admin.self_review.enabled: true` 时，daemon 在每日本地时间 `admin.self_review.run_at`（HH:MM，缺省 22:00）后由 Administrator Agent 执行一次当日工作回顾。数据源包含当日 STATE 终态分布、runs 统计（成功/失败/秒挂/超时/丢弃计数）、admin 告警与处置记录、日志 ERROR 聚合。`enabled: false` 时全链路零动作（不调度、不执行、不写文件）。
- 防重复与补跑：同一自然日至多执行一次（以状态文件 `last_run_date` 判定）；daemon 启动时若发现当日 run_at 已过且今日尚未执行，在启动后补跑一次；跨日后计数归零恢复调度。
- todo.md 结构化追加：以 markdown 追加（不覆盖历史）写入项目根 `todo.md`，每日一个 `## YYYY-MM-DD` 分节，内含「浪费」「失误」「可改进」三个小节；每条含证据（具体数字/事件）与建议动作，条目清晰度标准为「未参与当日工作的新 agent 可据此直接起草 SPEC 提案」。todo.md 不存在时创建。写入成功后自动 commit（仅含 todo.md 路径）并尝试 push，失败降级 WARNING、不影响下次追加。
- 归因证据边界：自省条目「调查评估」凡涉及根因归因，结论层级必须与当日可回收证据（失败明细档/告警/日志/commit）的覆盖层级一致。证据只覆盖失败形态（如失败明细 items 为空、fallback_full=true、total=0）、不足以在多个根因假说间裁决时，结论写「根因未定、多假说并存」并列出假说，MUST NOT 给出单因确定性归因，MUST NOT 据此建议针对特定根因的修复方向（如按「模型改坏代码」假说建议预检重跑）；建议动作仍须给出，但转向取证/止损方向（如补齐失败面明细留存、加预检），不依赖未证实的根因假说。当日存在直接证据钉死单一根因（如根治提交自述、可复现的最小证伪）时，才写确定性归因并附证据引用（commit/日志行/明细档字段值）。边界是「证据层级=结论层级」，不是禁止归因。
- 归因纠错不回改历史：后续窗口核实出既有条目的根因归因有误时，以新条目显式更正（写明证据与正确结论），不回改历史条目原文——todo.md 历史由每日自省的 git 提交固定，回改破坏审计链。
- 纪律承载层：归因层级是语义判断，`core/self_review.py` 对 analysis 字段仅格式化渲染、不生成内容，代码层不设归因层级机械校验；该纪律由 `agents/self-review.md`「调查评估」质量标准段承载（模板经 prompt_builder 装载、缺失 fail-fast，改模板即生效）。纪律未生效的观测信号为后续窗口再现「证据只覆盖形态却单因归因」。
- 上下文阅读开关：`admin.self_review.read_todo: true` 时自省派发 prompt 的「近 3 日既有条目」段注入窗口内既有条目的带 ID 标注清单（供识别历史条目、避免重复、标注已闭环项）；窗口内确无条目时该段为「近3日窗口内无既有条目」——此为真收集后的可核实结论。false（缺省）时该段为归因 read_todo 关闭的显式未收集陈述（如「（read_todo 关闭，未收集既有条目）」）——未收集与收集为空两种状态在输出文案上必须可分辨，未收集态不得呈现为空结论。未收集陈述在自省 detail 组装侧显式注入，不落入 prompt 组装的空清单兜底文案。
- 立项权保留：自省链路不依据 todo.md 条目自动创建 SPEC、注册 STATE 条目或派发 implementer——SPEC 立项判定权保留给用户；自省产出与 todo.md 仅供阅读。
- 摘要夹具过滤：日审数据摘要装配识别项目 fixture 标记（复用 dashboard registry 既有读取入口）——标记项目的告警不计入未处理告警计数，以显式 fixture 标注单独呈现或整体省略，MUST NOT 与真实项目告警混排；告警记录本身不删不改。标记读取失败或项目未标记一律按非夹具处理（fail-open），不因标记异常使摘要失效；无标记项目的计数口径与摘要结构不变。
- 配置界面：`admin.self_review` 三键（enabled/run_at/read_todo）在 Dashboard 设置页提供读写界面，enabled 与 read_todo 为开关控件、run_at 为时间输入（HH:MM 前后端双重校验，非法输入被拒）；保存后经既有配置热更新生效，无需重启 daemon。

## 溯源

- 2026-09-10 2026-09-10-add-daily-self-review（spec/archive/2026-09-10-add-daily-self-review） — 新增每日自省全链规则（定时调度与补跑防重、Administrator 通道执行、todo.md 结构化追加与自动提交、read_todo 开关、禁止自动立项、设置页界面）
- 2026-09-29 2026-09-29-evo-alert-noise-governance（spec/archive/2026-09-29-evo-alert-noise-governance） — 数据摘要装配新增夹具项目过滤：fixture 标记项目告警不进未处理计数、以 fixture 标注单独呈现，fail-open 不因标记异常失效
- 2026-10-12 evo-add-self-review-todo-fallback-honesty（spec/archive/2026-10-12-evo-add-self-review-todo-fallback-honesty） — read_todo 关闭时既有条目段改为归因「未收集」的显式陈述、与真收集为空的文案可分辨，判定点定在组装侧（治「未收集被呈现为近3日无条目、误导回顾 agent」）；read_todo 开启的收集与注入行为不变
- 2026-10-30 evo-self-review-evidence-bound-attribution（spec/archive/2026-10-30-evo-self-review-evidence-bound-attribution） — 「调查评估」新增归因证据边界纪律：结论层级与当日可回收证据覆盖层级一致，证据只覆盖失败形态时写多假说并存、禁单因确定性归因与定向修复建议（建议转取证/止损方向），有直接证据钉死才给确定性归因并附引用；归因纠错以新条目更正不回改历史；纪律落模板层、代码层不设机械校验
