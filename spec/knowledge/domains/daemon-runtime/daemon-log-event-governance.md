# daemon 日志单事件读写治理

<!-- knowledge: capability=daemon-log-event-governance rev=1
     sources=spec/archive/2026-10-30-improve-spec-topology-pipeline-view -->

daemon 结构化日志的单事件有界性：写侧序列化体积封顶、读侧锚定窗口对超长行健壮——单个巨型事件不再撑爆日志窗口、不再令锚点后事件整体丢失。

## 规则

- **写侧单事件序列化体积上限**：daemon 日志写侧序列化出口（`core/logger.py` 的 `json.dumps` 处）对单条日志事件设序列化体积上限（`LOG_EVENT_MAX_BYTES`，默认 256KB 量级常量可调）——序列化结果超限时，context 以占位摘要替换后重新序列化（保证产出仍是合法 JSONL 单行），占位摘要含 `truncated: true`、近似原体积与 context 顶层键名；message 本体不因 context 截断而丢失。context 替换后重新序列化仍超上限（message/exc_info 单体超限）时，允许对超限字段尾部截断并同样附 `truncated: true` 留痕——「落盘单行 ≤ 上限」在任意输入下可达。常规体量（< 上限）事件序列化结果逐字节不受影响（无 truncated 标记、无字段改动）。
- **读侧锚定窗口跳过超长行**：日志锚定窗口读取（`core/dashboard/data/log_index.py` 的窗口读取与块索引探测）对超长行健壮——块首行探测遇到无行界超长内容时，探测该块内第一个可定位行界之后的行，MUST NOT 整体放弃回退文件头；窗口读取遇到超长行时 seek 越过其内容（不将超长行整体读入内存）继续读取其后事件，单请求内存占用保持有界（单行上限阈值 + 窗口上限双重约束）；截断标记语义不变（按最终读取终点判定）。常规日志（不含超长行）窗口读取结果与无防御时一致（同起点同终点同截断标记）。

## 关键行为

消费链：状态转移派生（transitions）、SPEC 日志锚定窗口读取均依赖「锚点时刻之后的可解析事件不因单个巨型行丢失」。巨型行的两个来源被分别治理：存量已落盘巨型行由读侧 seek 跳过；新事件由写侧封顶截断留痕（占位摘要保留顶层键名与原体积，足以定位「哪类事件被截断」）。

## 溯源

- 2026-10-30 improve-spec-topology-pipeline-view（spec/archive/2026-10-30-improve-spec-topology-pipeline-view） — 新增本能力：写侧序列化体积上限（context 占位摘要替换 + truncated 留痕，动因实测 admin_monitor 信号嵌入 51054 个 untracked entry 撑出 6.6MB 单行）、读侧锚定窗口探测跳行与 seek 越行（锚定窗口 transitions 派生恒 0 的根因治理）
