<!-- knowledge: capability=daily-self-review rev=2 sources=spec/archive/2026-09-10-add-daily-self-review,spec/archive/2026-09-29-evo-alert-noise-governance -->

# 每日定时自省

daemon 每晚由 Administrator Agent 自动复盘当日运行（浪费/失误/可改进），结构化追加到项目 todo.md，为 SPEC 立项提供可追溯输入。

## 现行规则

- 定时执行：`admin.self_review.enabled: true` 时，daemon 在每日本地时间 `admin.self_review.run_at`（HH:MM，缺省 22:00）后由 Administrator Agent 执行一次当日工作回顾。数据源包含当日 STATE 终态分布、runs 统计（成功/失败/秒挂/超时/丢弃计数）、admin 告警与处置记录、日志 ERROR 聚合。`enabled: false` 时全链路零动作（不调度、不执行、不写文件）。
- 防重复与补跑：同一自然日至多执行一次（以状态文件 `last_run_date` 判定）；daemon 启动时若发现当日 run_at 已过且今日尚未执行，在启动后补跑一次；跨日后计数归零恢复调度。
- todo.md 结构化追加：以 markdown 追加（不覆盖历史）写入项目根 `todo.md`，每日一个 `## YYYY-MM-DD` 分节，内含「浪费」「失误」「可改进」三个小节；每条含证据（具体数字/事件）与建议动作，条目清晰度标准为「未参与当日工作的新 agent 可据此直接起草 SPEC 提案」。todo.md 不存在时创建。写入成功后自动 commit（仅含 todo.md 路径）并尝试 push，失败降级 WARNING、不影响下次追加。
- 上下文阅读开关：`admin.self_review.read_todo: true` 时自省 prompt 包含既有 todo.md 全文（供识别历史条目、避免重复、标注已闭环项）；false 时 prompt 不含 todo.md 内容。缺省 false。
- 立项权保留：自省链路不依据 todo.md 条目自动创建 SPEC、注册 STATE 条目或派发 implementer——SPEC 立项判定权保留给用户；自省产出与 todo.md 仅供阅读。
- 摘要夹具过滤：日审数据摘要装配识别项目 fixture 标记（复用 dashboard registry 既有读取入口）——标记项目的告警不计入未处理告警计数，以显式 fixture 标注单独呈现或整体省略，MUST NOT 与真实项目告警混排；告警记录本身不删不改。标记读取失败或项目未标记一律按非夹具处理（fail-open），不因标记异常使摘要失效；无标记项目的计数口径与摘要结构不变。
- 配置界面：`admin.self_review` 三键（enabled/run_at/read_todo）在 Dashboard 设置页提供读写界面，enabled 与 read_todo 为开关控件、run_at 为时间输入（HH:MM 前后端双重校验，非法输入被拒）；保存后经既有配置热更新生效，无需重启 daemon。

## 溯源

- [2026-09-10 2026-09-10-add-daily-self-review](spec/archive/2026-09-10-add-daily-self-review/) — 新增每日自省全链规则（定时调度与补跑防重、Administrator 通道执行、todo.md 结构化追加与自动提交、read_todo 开关、禁止自动立项、设置页界面）
- [2026-09-29 2026-09-29-evo-alert-noise-governance](spec/archive/2026-09-29-evo-alert-noise-governance/) — 数据摘要装配新增夹具项目过滤：fixture 标记项目告警不进未处理计数、以 fixture 标注单独呈现，fail-open 不因标记异常失效
