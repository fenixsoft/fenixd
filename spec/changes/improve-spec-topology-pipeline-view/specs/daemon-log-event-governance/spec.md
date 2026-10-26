## ADDED Requirements

### Requirement: 日志写侧单事件序列化体积上限

daemon 日志写侧（`core/logger.py` 序列化出口，`json.dumps(entry, …)` 处）对单条
日志事件设置序列化体积上限（默认 256KB 量级，常量可调）：序列化结果超限时，
context 以占位摘要替换后重新序列化（保证产出仍是合法 JSONL 单行），并附带
`truncated: true` 留痕标记；message 本体不因 context 截断而丢失。

#### Scenario: 巨型 context 事件被截断留痕

- **WHEN** 某日志事件 context 序列化后远超上限（实测样本：admin_monitor 信号
  嵌入 51054 个 untracked entry，单行 6.6MB）
- **THEN** 落盘单行体积 ≤ 上限（含开销余量），行内含 `truncated: true` 标记，
  message 字段完整保留

#### Scenario: 正常事件原样写入

- **WHEN** 常规体量（< 上限）的日志事件写入
- **THEN** 序列化结果与修复前逐字节一致（无 truncated 标记、无字段改动）

### Requirement: 日志读侧锚定窗口跳过超长行

日志锚定窗口读取（`core/dashboard/data/log_index.py` `_read_log_window_from` 及
块索引探测）对超长行健壮：

- 块首行探测遇到无行界超长内容时，探测该块内第一个可定位行界之后的行，
  而非整体放弃回退文件头；
- 窗口读取遇到超长行时跳过其内容（seek 越过，不将超长行整体读入内存），
  继续读取其后事件，单请求内存占用保持有界。

#### Scenario: 窗口被巨型行占满时仍读到锚点后事件

- **WHEN** created 锚点落在 6.6MB 巨型行之后、默认窗口（1MB 量级）起点被巨型行占据
- **THEN** 读取结果包含锚点时刻之后的可解析事件行，`_scan_spec_log_events`
  可派生出该 SPEC 的状态转移

#### Scenario: 超长行内容不整读入内存

- **WHEN** 窗口读取路径经过超长行（> 单行上限阈值）
- **THEN** 该行内容被 seek 越过（单请求读取字节数有界），不出现一次性读入
  超长行全文的内存峰值

#### Scenario: 常规日志窗口行为不变

- **WHEN** 日志不含超长行（常规 jsonl）
- **THEN** 锚定窗口读取结果与修复前一致（同起点同终点同截断标记）
