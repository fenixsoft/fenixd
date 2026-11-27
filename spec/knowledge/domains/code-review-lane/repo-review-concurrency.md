<!-- knowledge: capability=repo-review-concurrency rev=2 sources=spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience,spec/changes/evo-code-review-subagent-429-throttle,spec/changes/evo-add-code-review-429-fanout-throttle -->

# 全仓审查并发约束与 429 节流

全仓审查 run 的并行审查度由单一配置键约束，同时注入子代理扇出上限与 ocr scan 并行度两个通道；围绕账户级 429 限流形成三层节流——静态缺省降档、跨 run 记忆折减与 run 内记忆条款，防止扇出打爆共享 provider 账号。

## 现行规则

- 配置键 `verify.repo_code_review_concurrency`：正整数，缺省 2，一键两用（提示词侧并行扇出上限 + `ocr scan --concurrency` 缺省并行度，两通道同时生效；审查车道自身已不调用 ocr scan）。读取为 fail-open 单点缺省——仅接受正整数 `int`（`bool` 不算），键缺失/verify 节缺失/str/非整值 float/≤0 一律回退缺省 2，脏值不中断派发。缺省同源面三处保持一致：读器缺省、prompt_builder 注入段 fail-open 回退值（含 ConfigLoader 导入失败分支硬编码）、设置页前端常量 `REPO_REVIEW_DEFAULT_CONCURRENCY`；config.template.yaml 模板示例值等于缺省值（否则模板派生配置恒为显式旧值，缺省调整失效）。已显式配置的项目不受缺省影响。
- 管辖范围：只控制**全仓审查** run（`review_kind` 为 `manual_full` / `manual_window` / `scheduled`）的并行审查度；implement 任务内审查由 `verify.impl_code_review_concurrency`（缺省 4）控制，两键独立、互不串扰。code-fix 车道的波内并发是独立分档链（按文件组数分档），不在本键管辖，仅受下方 run 内记忆条款约束。
- 并发双通道注入：全仓审查 run 派发时并发值同时注入两处——① 提示词写入并行扇出上限条款：主 agent 同时在飞的审查子代理数 MUST ≤ 该值（波内并发上限而非任务总数上限，波次滚动推进）；② `ocr scan` 命令 MUST 带 `--concurrency <n>`（ocr 不传参时其内部缺省 8，不受本键约束）。设置页 QualityPanel 与「SPEC 审查并发」并列展示、分别保存。
- **跨 run 429 记忆折减**：run 启动注入扇出上限前，扫描上一轮同车道（code-review）归档 run 的 jsonl 尾部窗口——存在 429 终态（HTTP 429 / 错误码 1302 / rate_limit 签名）子代理死亡记录时，本次注入上限折减至 1（单轮记忆，不回溯更早轮次）；扫描缺失/异常按原配置值放行（fail-open，不阻塞派发）。
- **run 内 429 记忆条款（提示词契约）**：code-review 与 code-fix 模板均含 429 记忆条款——run 内一旦出现子代理 429 终态死亡，后续波次在飞上限 MUST NOT 回升，重派前等待 ≥60 秒、同 run 第二次 429 后 ≥180 秒；code-review 模板另含 429 处置条款——429 死亡后一律串行派发（在飞 1）、重派按 60s→120s→240s 指数退避、连续 3 个及以上子代理派发后 60 秒内秒死即止损：停止派发子代理转主循环自行逐文件审查，并在完成统计行末追加 `[review_429_storm=true; failed_shards=<n>]` 标记（该标记是 run 主体唯一额外输出通道，MUST ONLY 真实止损时追加）。两条款并存、按更严格者执行；违反沿「违反 = run 判失败」语义；退避等待期间继续自审未派发文件（轮询等待不是收工）。
- **429 风暴双告警通道**：① run 收尾扫描本 run jsonl 统计 429 终态子代理死亡数，≥3 经 AdminStore append_if_absent 直写单条 `review_subagent_ratelimit` 告警（dedup_key 含 run id，同 run 至多一条，少于 3 条不发；不入处置链防自环）；② 收尾解析完成统计行风暴标记回填结果信封（`review_429_storm` bool / `failed_shards` int；run 主体漏报保持缺省，零假阳性），admin_monitor 终态消费该标记落恰好一条 `review_429_storm` 告警（同 run 去重，建议文案含「同账户多项目审查窗口重叠、建议错峰排程」）。两通道与既有 run 级 `ratelimit_redispatch` 终局重派按 run 终态天然互斥（run 被打杀时风暴标记无从产生），无重复告警面；provider/run 级防线（provider_circuit 冷却、配额重置冻结、终局重派）管「该不该派这个 run」，扇出层管「run 内派多少子代理」，两层正交。

## 溯源

- 2026-09-30 add-code-review-concurrency-and-429-resilience（spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience） — 新增全仓审查并发键（当时缺省 4，fail-open）与提示词扇出上限、ocr scan `--concurrency` 双通道注入及设置页配套；起因是全仓审查多通道并发无上限打死网关账号
- 2026-11-27 evo-code-review-subagent-429-throttle（spec/changes/evo-code-review-subagent-429-throttle） — 缺省降档三同源面 4→2；派发契约新增 429 处置条款（串行降档、60/120/240s 指数退避、连续秒死止损转自审、完成统计行 `[review_429_storm=true; failed_shards=<n>]` 标记）；收尾解析标记回填结果信封并由 admin_monitor 落恰好一条 review_429_storm 告警（动因：fenix-desktop 连续两晚 429 风暴各死 3 子代理、单 run 成本推高到 $19-20 且 admin 告警零落账）
- 2026-11-27 evo-add-code-review-429-fanout-throttle（spec/changes/evo-add-code-review-429-fanout-throttle） — 同题并行立项的扇出层补强：模板键示例值同步 2（示例值必须等于缺省值）、跨 run 记忆折减至 1（上轮同车道归档 run 尾窗扫描、fail-open）、code-review/code-fix 双模板 run 内固定间隔记忆条款（≥60s / 第二次后 ≥180s）、收尾 ≥3 死亡 review_subagent_ratelimit 直写告警；与上条的同题重叠按「退避条款并存按更严格者执行、双告警通道并存（jsonl 收尾直写 + 统计行标记解析消费）」落地（动因同源：11-24 事故 b2/b3 秒死后契约无记忆、重派再死）
