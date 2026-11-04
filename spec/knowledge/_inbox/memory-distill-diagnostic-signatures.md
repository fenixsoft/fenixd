# memory 存量蒸馏：诊断噪音签名与误诊防护清单

## 背景

auto-memory 存量中反复出现「把噪音当故障」的误诊教训，沉淀为**签名→正确解读**
对照清单。适合折叠进 run-resilience / admin-ops / cost-observability 域的诊断类
能力页。

## 结论（签名 → 正确解读）

- **CLI stderr `unrecognized_model`**：自定义 BASE_URL 下每次请求都写但照发请求，
  成功 run 也高频出现——是诊断噪音勿当死因；但 **400 unrecognized model 不重试
  一次死**（CLI 重试白名单只有 5xx/429/断连/流停滞）。runner 拼 error 用 stderr
  末 5 行→死因常被该噪音误标。评审/蒸馏 run 报 unrecognized_model + Exit code 1
  连续 3 次=真故障（会冻结转人工）。网关「连得上但不响应」（TCP 黑洞）不触发
  failover——只认「失败」不认「挂」，run 以 ~1 轮/10min 蠕动到监督上限。
- **exit 143**：成批同刻=daemon shutdown 屠杀；离散个位数=CLI 自身网关错误
  （恒 exit 1）。排查 exit 143 先看是不是 agent 自杀——`ps aux | grep "[p]ytest"`
  会命中 agent 自己的 claude -p 进程（提示词文本嵌着命令字面量），kill 该 PID=自杀。
- **`duration_ms` 不可信**（见 ops 手册）；**stream-json usage 全零**：网关路由模型
  的 usage 字段恒 0（billing 面板对网关 agent 恒 0），直连 provider 才有值——不是
  采集 bug。
- **在飞 run 识别**：STATE `implementer_run` 只在完成态才写；「implementer_run=null
  + status=implementing + 分支有提交」是在飞正常态而非异常。分支有提交/tasks 已勾
  ≠ run 结束。`find_impl_run_file` 按 mtime 选 run 与 STATE 权威源脱节（启动清扫会
  抬高僵尸 mtime 污染判定）。
- **「锁冲突」**：两起取证均为同一 run_id 重复派发，非残留锁。
- **spec→分支/run 流枚举禁 glob 前缀匹配**：spec 名互为前缀时跨 spec 误归属
  （fenix/evo-add-fast-track-scale-precheck-* 命中 5 条、2 条属 -4afdbe 实证）；
  精确归属约定在 `worktree_manager.find_worktree_by_spec`。
- **转录前缀盲区**（详见 ops 手册条目）：planner 系前缀 + worktree 目录 impl- 前缀
  矛盾——流缺失不作否定判据。
- **「已修复问题复发」取证三轴**：提交时间轴 / 事故时间轴 / daemon 重启时间轴五锚
  对齐——「已修」可能只是修在了从未重启的进程之外（旧码窗口）；fastlane 曾同轮
  双计验证轮推高冻结计数（假复发）。
- **自省报告归因不可信**：`.fenix/todo.md` 自省条目的「证据」段可信，「调查评估/
  根因」段 8 条错 3 不可直接采信——立项前必须回源码/run jsonl 独立复核。
- **日志文案位置≠根因位置**：「planner 臆测端口」假归因（端口号是应用源码声明的
  默认值，planner 读对了，动端口的是框架 `{port}` 注入；那条日志字符串全库只在
  legacy 兜底段）——归因前先查日志字符串的代码归属层。
- **证据截断污染断言**：验证引擎 64KB 截断若作用于断言输入（先截断再 json.loads），
  >64KB 输出必然假失败（api/cli 已修，web 无此问题）；「先截断再解析」是通用反模式。
- **dashboard 生命周期枚举**：`_LIFECYCLE_ORDER` 漏登记新状态→哨兵把正常推进判成
  「状态回退」；「状态门控设计随新状态引入而过时」是复发模式（修改状态弹窗调度
  区块 ready 限定过时热修为第三例）——新状态引入须排查前端 status 枚举条件。
- **registry 误报族**：projects() 10s TTL 缓存「写后读」盲区——改变项目集的
  mutation 后必须 invalidate_projects_cache，否则已删项目消失→重现→10s 后再消失。
- **测试假失败签名**：`+++++++ Timeout +++` 横幅密集 + pytest 直接子进程出现
  `python3 -c time.sleep(60)` 孤儿=全局 Popen fake 泄漏连坐（test_run_stop_loss
  型自毒化，见 agent/prompt 规则条目）；裸 worktree 回归遇 gitignored dist 依赖
  用例=每批首回归必假失败（该两用例已删根治）。
- **VERDICT 时区混用**：「17:28」与「09-28 09:28」曾是同一事件的 UTC/本地混写——
  跨源时间对齐先统一时区。

## 证据

- 源记忆：fenixd-run-forensics-family、fenixd-gateway-blackhole-no-failover、
  fenixd-review-failover-invalid-model-freeze、fenixd-inflight-run-identification、
  fenixd-lock-conflict-is-duplicate-dispatch、fenixd-spec-branch-glob-prefix-misattribution、
  fenixd-fastlane-doublecount-freeze-forensics、fenixd-selfreview-attribution-unreliable、
  fenixd-evidence-truncation-pollutes-assertion-input、fenixd-lifecycle-order-unregistered-reviewing、
  fenixd-projects-ttl-cache-write-read-blindspot、fenixd-planner-family（假归因段）、
  fenixd-status-modal-scheduling-ready-gate-stale、fenixd-parse-bugs-status-enum-drift、
  fenixd-verdict-retry-misattribution-incident、fenixd-timestamps-all-utc。
- 2026-11-04 在飞实例：`spec/knowledge/log.md` 11:35 起 distill/fold 报
  `Claude Code doesn't recognize the model "glm-5.3-flash"` + exit=1——即「400
  unrecognized model 不重试一次死」签名（此前同参数轮次成功，疑 provider/模型
  配置侧变动，待查）。
