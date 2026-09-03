## ADDED Requirements

### Requirement: spec 摘要内存索引

Dashboard 服务端维护每项目 `{spec_name → spec_summary}` 摘要索引，供 `/api/specs` 与 SSE 广播读取。
索引以惰性构建（首次 `/api/projects` 或 watcher 首轮扫描触发）；每 spec 记录其依赖文件签名
（tasks.md / specs 目录 / .openspec.yaml / runs 目录 / verify-progress 文件，mtime_ns+size 键），
任一路径先比对签名，未变则直接返回缓存摘要，变化只重算该 spec 一条。

#### Scenario: 未变化返回缓存
- **WHEN** 索引构建完成后连续两次请求 `/api/specs?project=<p>`，期间该 spec 全部依赖文件无修改
- **THEN** 第二次请求直接命中缓存，不再发生 tasks.md / runs / specs 的任何文件读取（以调用计数或 strace 文件打开数断言为 0 增量）

#### Scenario: 单 spec 变更只重算一条
- **WHEN** 修改某 spec 的 tasks.md 后请求 `/api/specs`
- **THEN** 仅该 spec 的摘要被重算，其余 N-1 个 spec 命中缓存；响应中该 spec 的 task_done/task_total 反映新值

#### Scenario: STATE.md 变更全量重建
- **WHEN** 向 STATE.md 新增一个 spec 条目
- **THEN** 索引触发该项目全量重建，新 spec 出现在 `/api/specs` 响应中

### Requirement: 配置解析签名缓存

`read_effective_config` 与 `read_spec_mode` 按 `(resolved_path, mtime_ns, size)` 缓存解析结果；
mtime/size 未变时不再重读文件与 YAML 解析。缓存不设条目上限（键与 spec 数线性）。

#### Scenario: 配置缓存命中
- **WHEN** 连续两次调用 `read_effective_config(proot)`
- **THEN** 第二次调用不读 config.yaml 文件且不触发 YAML 解析（yaml safe_load 调用计数不变）

#### Scenario: 写回后自然失效
- **WHEN** 通过 `write_config` 或直接编辑修改 config.yaml（mtime 变化）
- **THEN** 下一次读取解析新内容，旧缓存不生效

### Requirement: cleanup_runs 节流

`cleanup_runs` 对同一项目 60 秒内只实际执行一次清理；节流期内调用直接返回（幂等）。

#### Scenario: 节流生效
- **WHEN** 1 秒内连续两次调用 `cleanup_runs(proot)`
- **THEN** 第二次调用不产生任何文件删除/目录遍历（以执行标志或计时断言）

## CHANGED Requirements

<!-- 无 -->