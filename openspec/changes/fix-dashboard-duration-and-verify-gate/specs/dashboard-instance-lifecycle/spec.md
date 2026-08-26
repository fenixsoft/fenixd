## ADDED Requirements

### Requirement: dashboard 端口独占与启动语义

`fenix_dashboard.py --serve` 启动时若目标端口已被占用，MUST NOT 静默僵挂：需检测端口占用者，若为旧的 `fenix_dashboard.py --serve` 实例（命令行匹配 `bin/fenix_dashboard.py` 且含 `--serve`），MUST 先终止旧实例再绑定接管端口；若占用者为其它进程（非 dashboard 实例），MUST 明确报错退出并提示占用信息。同一时刻 MUST 至多一个 dashboard 实例监听生产端口（端口号来自 `--port > dashboard.yaml port > config port > 默认 8787` 的现有解析链）。

任何情况下启动失败的实例 MUST 在 5 秒内退出进程，不得保留「已运行但未监听」的僵尸实例堆积。

#### Scenario: 旧 dashboard 实例占用端口时接管

- **WHEN** 端口 8787 已被 13:26 启动的旧 `fenix_dashboard.py --serve --port 8787` 实例占用，此时启动新的 `fenix_dashboard.py --serve --port 8787`
- **THEN** 新实例检测到占用者为 dashboard 旧实例，终止旧进程并成功绑定 8787；`curl :8787/api/specs` 返回最新代码字段（如 `total_duration`）

#### Scenario: 非 dashboard 进程占用端口时报错退出

- **WHEN** 端口 8787 被无关进程（如 nginx、其它服务）占用
- **THEN** 新实例打印包含占用进程信息的错误后退出，退出前不终止任何进程，状态码非 0

#### Scenario: 端口解析链保持现有语义

- **WHEN** 未传 `--port` 且 `dashboard.yaml` 与 config 均指定了端口
- **THEN** 采用的端口序仍为 `--port > dashboard.yaml port > config port > 8787`（仅对最终确定的单一端口做上述占用检测）