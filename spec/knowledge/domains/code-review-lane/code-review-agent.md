# 周期性代码审查 agent

<!-- knowledge: capability=code-review-agent rev=3
     sources=spec/archive/2026-09-24-add-code-review-agent-and-quality-tab,spec/archive/2026-09-27-add-code-review-scope-config,spec/archive/2026-09-29-add-code-review-sharded-out -->

项目级周期性代码审查的一等公民 agent 车道：由框架调度层按与每日自省同源的周期口径派发，对主树代码逐文件审查并增量落盘，支撑质量分面台账与手动触发。

## 规则

- `code-review` 是一等公民 agent 类型，注册点共四处，缺任一均视为实现不完整：
  - `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 含 `"code-review": "code-review.md"`；
  - `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 含 `("code-review-", "code-review")`；
  - `core/config.py` 的 `KNOWN_AGENT_TYPES` 含 `"code-review"`；
  - `.fenix/config.template.yaml` 的 `agents.models` 含 `code-review` 模型分配示例，框架根 `agents/code-review.md` 提示词文件存在。
- run_id 采用 `code-review-<epoch>` 形态；`infer_run_agent_type` 能将其归属到 `code-review`，Dashboard 时间线显示该 agent 类型而非泛型 `agent`。
- 模型分配回退链：`agents.models.code-review` → `self-review` → `administrator` → 默认网关；配置缺失时逐级回退，不静默直落默认网关。
- 周期口径与每日自省（`admin.self_review`）完全同源，不另立周期：`window_start` 取 `.fenix/self_review_state.json` 的 `last_run_at`，缺失（首跑/旧格式）回退 `now - 24h`；触发时点与自省 `run_at` 对齐；同一自然日不重复触发；`admin.code_review.enabled` 为 false 时全链路零动作（不派发、不写任何产物）。
- 审查范围经 `admin.code_review.scope` 配置，取值 `window`（缺省）| `full`；非法值（含缺失/类型错误）回退 `window`，不报错中断巡检。两档共用同一套调度守卫（`run_at` 对齐、自然日去重、单飞、开关零动作），`review_kind` 均保持 `scheduled`。
  - scope=`window`：审查对象为 `window_start` 之后合并/产出到主树的 SPEC 所变更的文件集合。
  - scope=`full`：审查对象为全仓受控源码文件（`collect_manifest(scope="full")`），经 `max_files` 上限截断；`window_start` 以 None 参与 run，manifest 审计字段如实记录 `full`。
- 派发逻辑位于框架调度层（daemon/admin_monitor）；`core/self_review.py` 硬约束不派发 agent。
- 框架侧在派发前算出审查 manifest（待审文件清单）并写入 prompt；manifest 长度是进度 `total` 的权威来源。
- 审查结果以「主产物 + 子代理分片」双轨落盘：主 agent 的汇总写主产物 `.fenix/code-review/out-<run_id>.jsonl`（逐文件追加，不等 run 结束一次性写出），并行子代理各自直写自己的分片 `.fenix/code-review/out-<run_id>-b<N>.jsonl`（`N` 为正整数）；落盘义务为「谁审谁写、审完即写」，不以主 agent 最后统一汇总为唯一落盘路径。
- 分片行的 JSON 结构与主产物行完全一致（逐文件一行，`findings` 为列表，空 findings 行也落盘）；非 `out-<run_id>-b<正整数>.jsonl` 形态的文件不被进度读侧/收尾 ingest/产物硬门任何一侧消费（错名分片由读侧 WARNING 点名，只告警不消费，不放宽发现口径兜错名）。
- 主 agent 不亲自重复审查已派发给子代理的文件；批次分片已落盘后不再重写该批行——同 `file` 重复行以先落盘者为准，读侧按 `file` 去重。
- 收到 `Async agent launched` 类元数据后，主 agent 不得以「等待批次完成通知」为由结束 run：非交互模式下 turn 结束即主进程退出，异步批次结果不可回收。主 agent 必须轮询分片落盘进度并同步推进自己的未派发批次，或不派子代理、全自行逐文件审查。
- 产物硬门（`repo-code-review-gate`）按聚合口径判存在性：主产物与全部分片的有效结果行合计为零（或全部缺失）判整轮失败；任一来源存在至少一行有效行即通过存在性校验（manifest 覆盖率校验口径不变）。
- 消费侧统一经唯一聚合入口取「分片 + 主产物」行，任何一侧不自写 glob 或另立读取口径（聚合与去重细节见 [code-review-progress-visibility](code-review-progress-visibility.md)）。
- `ocr` 可作为辅助审查手段；`ocr` 缺失或不可达时降级以 LLM 审查继续，不因辅助工具缺失整轮失败。
- 进度结构为 `{running, review_id, review_kind, total, done, current}`；`running` 判定基于该 run 产物 `.fenix/runs/<review_id>.jsonl` 末行是否属终态集合（对齐 runs 口径全量：`result`/`error`/`interrupted`/`cancelled`/`frozen-terminated`/`superseded`/`gate-blocked`），非终态再叠加 stale 阈值兜底；不以「产物/manifest 文件是否存在」近似判定（否则已取消/停机的 run 永远显示运行中，手动触发 409 守卫恒真）。
- 取消复用既有 run 取消机制（写 `.fenix/cancel_run_request.json` 旗标由 daemon 消费），不另立通道；取消后 run 终止，已落盘的部分结果保留。

## 溯源

- [2026-09-24 add-code-review-agent-and-quality-tab](spec/archive/2026-09-24-add-code-review-agent-and-quality-tab/) — 新建周期代码审查 agent：类型四处注册与模型回退链、自省同源周期调度、manifest 驱动逐文件增量落盘、真实进度与取消。
- [2026-09-27 add-code-review-scope-config](spec/archive/2026-09-27-add-code-review-scope-config/) — 审查范围经 `admin.code_review.scope` 扩为 window/full 两档（共用调度守卫），设置页「质量」页签新增「审查范围」下拉（当期审查/全库审查，非法回退 window）。
- [2026-09-29 add-code-review-sharded-out](spec/archive/2026-09-29-add-code-review-sharded-out/) — 产物落盘契约扩为主产物+分片双轨直写（落盘义务「谁审谁写」），追加禁 async 等待收工条款与产物硬门聚合口径；进度/台账/硬门三侧改聚合消费（读侧口径另立 code-review-progress-visibility 页）。
