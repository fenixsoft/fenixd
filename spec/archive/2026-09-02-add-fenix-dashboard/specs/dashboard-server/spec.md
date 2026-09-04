## ADDED Requirements

### Requirement: 多项目注册与发现
Dashboard 服务器 MUST 从 `~/.config/fenixd/dashboard.yaml` 读取监控配置，格式为：
```yaml
port: 8787
projects:
  - name: <别名>
    path: <项目绝对路径>
scan_dirs:
  - <父目录>
```
`discover()` MUST 合并显式 `projects` 与 `scan_dirs` 扫描结果；扫描时仅当目录同时存在 `STATE.md` 与 `.fenix/config.yaml` 才识别为 Fenixd 项目。`--add-project <path>` MUST 将指定项目写入配置（按路径去重，已存在则跳过），供 skill 与 CLI 调用。显式 `projects` 中的项目 MUST 始终出现于监控列表（即使扫描未命中）。

#### Scenario: 配置 + 扫描合并发现
- **WHEN** 配置中显式注册项目 A，且 `scan_dirs` 指向的目录下存在满足条件的项目 B
- **THEN** 监控列表同时包含 A 与 B，且每个项目包含 name、path、是否自动发现标记

#### Scenario: 误检目录被排除
- **WHEN** `scan_dirs` 下的目录只有 `STATE.md` 而无 `.fenix/config.yaml`
- **THEN** 该目录不进入监控列表

#### Scenario: 注册项目去重
- **WHEN** 对已注册的项目路径再次执行 `--add-project`
- **THEN** 配置中不产生重复条目，且返回已存在的提示

### Requirement: 聚合数据 API
Dashboard 服务器 MUST 提供以下 REST JSON API（仅监听 127.0.0.1）：
- `GET /api/projects`：监控项目列表及各自聚合摘要；
- `GET /api/overview`：跨项目状态统计（各 status 的 SPEC 数）、任务总进度、问题/阻塞数、活跃运行数；
- `GET /api/specs?project=<name>`：某项目全部 SPEC 摘要（状态、优先级、错误、任务进度、验证进度、最新运行）；
- `GET /api/specs/<spec>?project=<name>`：单个 SPEC 完整详情（任务分组、验证进度、场景级测试结果、bug 列表、截图列表、运行记录）；
- `GET /api/runs/<run_id>?project=<name>`：单次运行的产物流（LLM 事件列表、终止状态）；
- `GET /api/events?project=<name>&minutes=N`：最近 N 分钟的结构化事件（来自 `.fenix/logs/fenixd*.log`）。
以上 API MUST 以 `application/json` 返回，解析失败的数据源（如损坏的 progress 文件）MUST 以容错方式跳过并以字段标记，不使整个请求失败。

#### Scenario: 概览聚合统计正确
- **WHEN** 两个项目分别有多个处于不同状态的 SPEC
- **THEN** `/api/overview` 返回各 status 计数与任务进度按项目正确聚合

#### Scenario: 损坏数据源容错
- **WHEN** 某项目的 `.fenix/verify-progress/<spec>.json` 内容损坏或非对象
- **THEN** 相关 API 仍正常返回，该 SPEC 的验证进度字段标记为异常或空，不导致请求 500

### Requirement: 截图等静态资源安全服务
服务器 MUST 提供 `GET /screenshots/<project>/<spec>/<file>` 服务项目的 `.fenix/verify-progress/<spec>/screenshots/` 下 PNG 截图，返回正确的 `image/png` MIME。路径解析 MUST 经 `Path.resolve()` 校验解析后路径仍位于该项目 `screenshots` 目录内（防路径穿越）；`project` MUST 存在于注册项目列表，`spec` 与 `file` 段不合法时返回 404/403。

#### Scenario: 正常展示截图
- **WHEN** 请求已注册项目的合法 spec 下存在的 PNG 截图
- **THEN** 返回 200 与 `image/png` 内容

#### Scenario: 路径穿越被拒绝
- **WHEN** 请求 `/screenshots/<project>/<spec>/../../../etc/passwd` 之类的路径
- **THEN** 返回 403 或 404，不暴露文件内容

### Requirement: 独立进程与端口管理
Dashboard MUST 以独立进程运行（可由 `bin/fenix_dashboard.py --serve` 启动），默认端口 8787，可被 `--port` 覆盖。启动时若端口被占用，MUST 自动向上探测下一个空闲端口并使用，同时在启动输出中打印实际 URL。服务器 MUST 仅绑定 127.0.0.1。

#### Scenario: 端口被占用时自动切换
- **WHEN** 默认 8787 已被占用
- **THEN** 服务在下一个空闲端口启动，并在输出中给出实际访问 URL

#### Scenario: 仅本机可访问
- **WHEN** 从非 127.0.0.1 的地址访问服务
- **THEN** 无法建立连接（绑定仅限 127.0.0.1）
