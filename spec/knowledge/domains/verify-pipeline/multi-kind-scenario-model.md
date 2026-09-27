# 多类型验证场景模型
<!-- knowledge: capability=multi-kind-scenario-model rev=1 sources=spec/archive/2026-09-12-add-verify-multi-kind-runner -->

场景级 `kind` 字段（web/cli/api）与三套结构化词表：单一场景不混排、跨 kind 用 depends_on 编排，断言分层语义跨 kind 统一。

## 现行规则

- kind 字段与缺省兼容：`TestScenario.kind` 取值限定 `{web, cli, api}`，缺省 `web`；`from_dict` 对缺失 `kind` 的存量场景文件按 `web` 处理（存量零迁移）；非法 kind 报「未知 kind」拒绝，不静默按 web 处理。
- 单场景单 kind：单个场景内全部步骤属于同一 kind 的词表，不混排；同一场景集内不同场景可混用 kind；`depends_on` 允许跨 kind 引用，拓扑排序保证被依赖场景先完成；场景 id 在场景集内全局唯一。场景内混排步骤（如 api 场景出现 `click`）报错打回 plan。
- CLI 词表：步骤限定 `run`（`command` 字符串=shell 执行/列表=argv 直接执行、`cwd` 相对验证树根、`env` 支持 `{env:VAR}` 插值、`stdin`、`timeout`、`as` 命名结果）；断言限定 `exit_code`（缺省期望 0）、`file_exists`、`output_match`、`file_content`、`json_output`、`dir_contains`。
- CLI 执行语义：非零退出码不判步骤失败（结果照常记录，由 `exit_code` 断言仲裁）；超时杀整个进程组判步骤失败（防孤儿子进程）；被信号终止（如段错误）判 `error` 而非 `fail`，不进 product-bug 管道；argv 二进制不存在判 `error`。stdout/stderr 捕获超 64KB 截断并带截断标记；场景结果 `screenshots`/`visual_results` 恒为空列表。
- API 词表：步骤限定 `http_request`（method/url/headers/body+body_type/timeout/as，URL 为绝对 URL、origin 由框架改写）与 `sse_connect`（url/duration/as）；断言限定 `status_code`、`json_path`、`response_header`、`body_contains`、`json_schema`、`latency_under`、`sse_event_matches`、`sse_event_count`。断言经 `response` 字段指向命名捕获（缺省=最近一次响应）；每个响应捕获 `{status, headers, body, json, latency_ms}`，`sse_connect` 捕获窗口内事件列表；响应体超 64KB 截断。
- 断言分层跨 kind 统一：第 1/3 层为确定性断言（失败=一定是 Bug）、第 4 层为启发式阈值断言（失败=warning）；`ASSERTION_LAYERS` 允许按 kind 稀疏（CLI/API 无第 2 层）；场景状态判定（步骤失败=fail、1-3 层断言失败=fail、仅 4 层失败=warning）对三种 kind 一致。
- per-kind 场景验收：验收委托所属 Runner 的 `validate`，校验本 kind 的 action/断言类型/必填字段（含 WebRunner 持有的 navigate 绝对 URL 硬要求）；未知 kind、跨词表步骤误用、必填字段缺失均报错。验收失败不启动任何 Runner、不执行任何场景，产出带 `env_error` 的空报告并退回 plan。

## 溯源

- 2026-09-12 add-verify-multi-kind-runner — 新增场景 kind 字段（缺省 web 零迁移）、CLI/API 两套词表与特异执行语义、断言分层跨 kind 统一、per-kind 验收校验（此前场景模型以 web 为唯一形态假设，纯 CLI/API 类 spec 在验收门即被整体拒绝）
