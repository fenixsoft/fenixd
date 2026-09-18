## MODIFIED Requirements

### Requirement: Dashboard 展示定时拾取倒计时并支持修改

spec 列表 MUST 对 `start_after` 未到期的 spec 展示定时拾取标记（含目标时间与倒计时，目标时间以本地时区渲染）。行操作菜单 MUST 提供「设置拾取时间」入口：可将 `start_after` 修改为新的时间点（本地时区输入，转 UTC 存储），也可清除定时（`start_after` 置 null，立即恢复调度）。

当 `start_after` 为哨兵值 `manual`（待激活态）时，MUST NOT 按时间戳渲染倒计时标记（该值非时间，倒计时无意义）；「设置拾取时间」弹窗对该值的预填 MUST 安全降级（不得因解析失败而报错或误清空），且「设置拾取时间」入口的写侧 MUST 接受哨兵值（用于设为待激活）与 null（用于清除/激活）。待激活态的展示与激活入口见 `spec-manual-activation` 能力。

#### Scenario: 列表展示等待标记

- **WHEN** spec A 的 `start_after` 为未来时间
- **THEN** 列表中 spec A 行展示定时拾取标记与目标时间、倒计时

#### Scenario: 修改拾取时间

- **WHEN** 用户在 spec A 行菜单选择「设置拾取时间」并提交新时间点
- **THEN** STATE.md 中 spec A 的 `start_after` 更新为新值，列表标记随之刷新

#### Scenario: 清除定时立即恢复调度

- **WHEN** 用户在「设置拾取时间」弹窗中选择清除定时
- **THEN** spec A 的 `start_after` 置 null，该 spec 在下一次派发评估中可被拾取

#### Scenario: 哨兵值渲染不误判为定时

- **WHEN** spec A 的 `start_after` 为哨兵值 `manual`
- **THEN** 列表不渲染定时倒计时标记（渲染「待激活」标记），打开「设置拾取时间」弹窗不报错

### Requirement: start_after 字段格式与边界语义

`start_after` MUST 为 ISO8601 UTC 时间戳、哨兵值 `manual` 或 null。写入路径（fenix-new 注册、dashboard 修改、evo 同意立项）MUST 校验格式，非法格式拒绝写入。`start_after` 早于或等于当前时间的值 MUST 等价于 null（不阻塞拾取）。哨兵值 `manual` MUST 恒被视为「未到期」（永久阻塞拾取，直至人工激活）。终态 spec（done/pushed）的 `start_after` MUST NOT 可被修改（写入路径拒绝），且其 `start_after` 不影响任何行为。

#### Scenario: 非法格式拒绝写入

- **WHEN** 修改请求携带 `start_after: "明天早上"`
- **THEN** API 返回错误，STATE.md 中该字段不变

#### Scenario: 过去时间等价无限制

- **WHEN** spec A 的 `start_after` 被设置为已过去的时间
- **THEN** spec A 在下一次派发评估中被正常拾取

#### Scenario: 哨兵值被接受为合法写入

- **WHEN** 写入请求携带 `start_after: "manual"`
- **THEN** 该值被校验为合法并写入 STATE.md（不被当作非法格式拒绝）

## ADDED Requirements

### Requirement: 读侧 start_after 识别哨兵值不折叠为 null

列表摘要读取入口 `get_spec_start_after(entry)`（dashboard 读侧规范化函数）SHALL 对哨兵值 `manual` 原样返回字符串 `"manual"`，SHALL NOT 将其折叠为 null（否则前端丢失「待激活」语义，无法渲染标记与激活入口）。对 null 与非法格式 SHALL 维持既有「返回 null（=无限制）」语义。

#### Scenario: 哨兵原样返回

- **WHEN** STATE.md entry 的 `start_after` 为 `manual`，调用 `get_spec_start_after(entry)`
- **THEN** 返回字符串 `"manual"`

#### Scenario: null 与非法值仍返回 null

- **WHEN** entry 的 `start_after` 为 null 或非法字符串（非 manual）
- **THEN** 返回 null（行为与本次变更前一致）
