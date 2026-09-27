# ADR-001：Agent 运行产物流式落盘协议

date: 2026-09-02
status: accepted

## Context

agent 以 `claude -p` 子进程运行，阻塞式 capture 模式下运行期不产生任何落盘输出，仅结束后的末 500 字摘要进日志。长跑 agent「正在干什么」不可观测；运行日志、取证、任务进度解析、孤儿/中断判定等下游能力都缺少统一的过程数据源。读 Claude Code 会话转录（`~/.claude/projects/`）依赖其内部布局，且跨项目路径脆弱。

## Decision

- 所有 agent 角色（implementer / verifier / planner / administrator）的 claude 子进程一律以 `--output-format stream-json` + `Popen` 逐行读取启动，事件原样追加写入 `.fenix/runs/<run_id>.jsonl`，不从会话转录侧取数。
- run_id 携带 attempt 序号（`<prefix>-<spec>-<unix_ts>-a<n>`），每次 attempt 对应独立产物文件；时间戳等解析职责集中在一处（读侧 `get_runs`），不改 run_id 生成格式。
- 文件任何时刻必须可逐行解析：非 JSON 行以 `{"type":"stderr","line":...}` 兜底落盘；异常/超时追加 `{"type":"error",...}` 终态行；daemon 优雅关闭追加 `{"type":"interrupted",...}` 终态行；attempt 启动时可写 `provider_marker` 行记录本次 provider/model。
- 最终返回值从文件内末个 `result` 事件还原，保证调用方拿到的结果语义与非流式模式等价。
- `.fenix/runs/` 只保留最近 N 个 run 产物（默认 20），启动/轮询时清理。

## Consequences

- 运行过程全程可观测、可取证，Dashboard 运行日志与各类读侧分析都以此为唯一数据源；下游对 jsonl 行类型形成协议依赖，新增行类型必须逐行容错兼容旧读取方。
- 半文件可读：被强杀的 run 保留已产出内容，便于诊断挂起。
- 产物目录有界，不随 run 数无限膨胀；run 文件被清理后依赖它的读侧能力（如进度解析）随之失效，需要落盘的能力不得只依赖 run 文件。
