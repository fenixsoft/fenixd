# codefix-affinity-batching 能力规格

code-fix 自动修复车道的选批亲和性聚类、批内波次上限自适应、批收尾回归两段式。

## ADDED Requirements

### Requirement: 选批按文件亲和性聚类

`select_batch` SHALL 以**文件组**（按条目 `file` 字段分组，同文件全部 open 条目归并为一个组）为最小不可拆单元进行贪心装箱，替代既有「时间序截取前 N 条」：

- 文件组间排序：按组内最早 `first_seen_at` 升序（缺失回退组内最小 `item_id`，与既有稳定序口径一致）；组内条目保持既有稳定序。
- 目录簇：直接父目录相同的文件组构成一个簇（无父目录的顶层文件互不为同目录）。
- 目标规模 T = `batch_size`（缺省 20，语义为「目标规模」而非精确条数）；硬上限 H = 2×T。
- 装箱规则（确定性，同输入必同输出）：
  1. 从最早的文件组开启当前批；
  2. 吸收候选优先级：与批内已有文件**同目录**的最早文件组优先；无同目录候选、或同目录候选不满足其吸收条件时，继续取全局最早的文件组尝试吸收；
  3. 吸收**同目录**组的条件：加入后批条数 ≤ H（允许超过 T）；
  4. 吸收**异目录**组的条件：当前批条数 < T；吸收后批条数 ≥ T 即封批；
  5. 批条数达到 H 后不再吸收任何组，封批；
  6. 单文件组自身条数 > H 时独立成批、MUST NOT 拆分（整批可超 H）。
- 排除口径不变：失败档案条目并集 ∪ `exclude_ids`（chain_skipped）不入选。
- 台账读失败时返回空列表的 fail-closed 行为不变。

#### Scenario: 同文件条目必同批

- **WHEN** 文件 `core/foo.py` 有 3 条 open 条目（first_seen_at 分别为 t1/t5/t9），另有文件 `core/bar.py` 2 条（t2/t3）、`util/baz.py` 1 条（t4），batch_size=20
- **THEN** `core/foo.py` 的 3 条在同一批（文件组按最早 first_seen_at=t1 排序参与装箱，组内归并），MUST NOT 被拆散到多个批

#### Scenario: 同目录文件超目标规模仍同批

- **WHEN** 当前批已含 `core/foo.py` 组 8 条，下一候选为同目录 `core/bar.py` 组 15 条（8+15=23 > T=20 但 ≤ H=40）
- **THEN** `core/bar.py` 组被吸收进当前批（同目录组允许浮动超 T，上限 H）

#### Scenario: 异目录组达到目标规模即封批

- **WHEN** 当前批已有 18 条（< T=20），下一候选为异目录组 5 条
- **THEN** 该组被吸收（18 < T 允许吸收），批条数变为 23 后立即封批（23 ≥ T）

#### Scenario: 硬上限封批

- **WHEN** 当前批已有 38 条，下一候选为同目录组 6 条（38+6=44 > H=40）
- **THEN** 该组不被吸收，当前批以 38 条封批；该组进入下一装箱批

#### Scenario: 单文件超大组独立成批不拆分

- **WHEN** 单文件组自身有 45 条（> H=40）
- **THEN** 该组独立成批且 45 条全部保留在批内（MUST NOT 为凑硬上限拆散文件组）

#### Scenario: 排除口径与稳定性不变

- **WHEN** 存在失败档案条目与 chain_skipped 条目，且以同一台账状态连续调用 `select_batch` 两次
- **THEN** 两次返回完全一致（确定性），且被排除条目不出现在任何批中

### Requirement: 批内并行波次上限自适应

code-fix run prompt 中的批内子代理并发上限 SHALL 随批内文件组数 G 分档，MUST NOT 再固定为 4：

- G ≤ 4 → 上限 4；5 ≤ G ≤ 8 → 上限 6；G ≥ 9 → 上限 8。
- 8 为硬上限（防网关限流放大），任何批规模 MUST NOT 超过。
- 上限值经 prompt 组装点（`_build_code_fix_prompt`）以占位符注入 `agents/code-fix.md`；模板中固定「≤4」的表述 MUST 同步改为占位符引用。
- 串行路径判定（仅 1 个文件组或总条目 ≤2 不派子代理）保持不变。

#### Scenario: 文件组数分档

- **WHEN** 批内文件组数分别为 3、6、12
- **THEN** 注入 prompt 的波次上限分别为 4、6、8

#### Scenario: 单文件大组批仍为下限 4

- **WHEN** 批为单文件组 45 条（G=1）
- **THEN** 波次上限为 4（下限），串行/并行判定逻辑不因批变大而变化

### Requirement: 批收尾回归两段式（中间批定向、末批全量兜底）

批收尾回归 SHALL 按「是否链内末批」分两段：

- **链末批判定**：批收尾时按链选批同口径排除（失败档案 ∪ `chain_skipped` ∪ 延迟台账）后、再排除本批 item_ids，若无剩余可选批条目（与 `select_batch` 返回空同判据）→ 本批为末批。MUST NOT 用不排除失败档案/跳过/延迟条目的裸 `count_open_items` 判定——链实际收敛的最后一批收尾时常有此类被排除 open 条目在档，裸计数 >0 会把该批判为非末批、走定向回归后链随即正常收敛，全量兜底防线整链落空。
- **末批**：恒走**全量回归**（verify.yaml regression 段原样执行），作为链收尾的合并防线；MUST NOT 末批定向。
- **非末批**：`admin.code_review_fix.targeted_regression` 为 true（缺省）时走**定向回归**——`regression.cmd` 含 `{test_targets}` 占位符时，框架按批触碰面映射出的测试路径列表替换占位符执行；否则（cmd 无占位符、映射结果为空集、或配置为 false）**回退全量回归**（fail-open 防漏检）。
- 触碰面映射（纯函数，可单测）：输入为本批产物 `fixed` 行的 `file` 集合——(a) 测试文件本身（`tests/` 下或 `test_` 前缀/`_test` 后缀）直接入选；(b) 产品文件按「同目录 `tests/` 的 `test_<stem>.py` 命名匹配」+「`tests/` 树内 import 该模块的文件」两条规则取并集；(c) 路径相对于回归执行根（worktree）解析。
- 定向回归 MUST 复用 `run_regression` 既有机制（`full-suite.lock` 主机级锁、JUnit XML 解析、`timeout_seconds` 硬超时），只缩小测试集、不新增执行通道；`{test_targets}` 占位符语义对齐 `{port}` 占位符先例（替换 + 同值导出 `FENIX_TEST_TARGETS` 环境变量，双轨）。
- 失败语义：定向回归失败与末批全量失败均走既有回归失败路径（含 add-codefix-targeted-retry 定向重试轮），MUST NOT 新增独立处置分支。
- 进度写点：回归阶段 `current` 文案区分「定向回归」与「全量回归」（批阶段文案不带分母）。

#### Scenario: 链末批恒全量

- **WHEN** 某批收尾时，按链选批同口径排除（失败档案 ∪ chain_skipped ∪ 延迟台账）与本批 item_ids 后无剩余可选批条目（台账仍可能存在被上述口径排除的 open 条目）
- **THEN** 该批走全量回归（无论 targeted_regression 取值、regression.cmd 是否含占位符）

#### Scenario: 非末批定向回归生效

- **WHEN** 非末批、targeted_regression=true、regression.cmd 含 `{test_targets}`、且触碰面映射结果非空
- **THEN** 回归命令中的 `{test_targets}` 被替换为本批映射出的测试路径列表后执行，MUST NOT 跑全量测试集

#### Scenario: cmd 无占位符回退全量

- **WHEN** 非末批、targeted_regression=true，但 regression.cmd 不含 `{test_targets}` 占位符
- **THEN** 该批回退全量回归（行为与现状一致，向后兼容零迁移）

#### Scenario: 映射空集回退全量

- **WHEN** 非末批、targeted_regression=true、cmd 含占位符，但本批 `fixed` 行的文件集映射不出任何测试路径
- **THEN** 该批回退全量回归（fail-open 防漏检），并记日志留痕

#### Scenario: 配置关闭回退全量

- **WHEN** `targeted_regression=false`
- **THEN** 所有批次（除末批恒全量外）均走全量回归，等价现状行为

#### Scenario: 触碰面映射规则

- **WHEN** 本批 fixed 文件集为 `core/foo.py`、`tests/test_foo.py`，且 `tests/test_bar.py` 内 import 了 `core.foo`
- **THEN** 映射结果包含 `tests/test_foo.py`（测试文件直接入选 + 产品文件命名匹配）与 `tests/test_bar.py`（import 反查）

#### Scenario: 定向回归失败走既有路径

- **WHEN** 非末批定向回归失败（status=failed）
- **THEN** 进入既有回归失败处置（定向重试轮按 add-codefix-targeted-retry 语义），不新增独立分支

### Requirement: targeted_regression 配置键与设置页界面

- 新增配置键 `admin.code_review_fix.targeted_regression`：严格 bool，缺省 true；非法值（非 bool 类型，如字符串 `"yes"`、整数 1）MUST 回退缺省 true 并记 warning（对齐既有配置项非法回退先例）。
- 设置页「质量」页签 `code_review_fix` 区块（`QualityPanel.tsx`，与 `code_review_fix_batch_size` 同区域）SHALL 新增该键的开关控件，经既有 GET/POST `/api/config` 通道读写。
- `.fenix/config.template.yaml` 的 `code_review_fix` 注释样例段 SHALL 同步新增该键（含语义说明：true=非末批定向、末批恒全量；false=全批全量）。

#### Scenario: 非法配置值回退缺省

- **WHEN** 配置中 `targeted_regression` 为字符串 `"yes"`
- **THEN** 运行时按缺省 true 处理，记 warning，MUST NOT 抛异常或中断批链

#### Scenario: 设置页开关读写生效

- **WHEN** 用户在设置页「质量」页签切换 targeted_regression 开关并保存
- **THEN** 配置经 POST /api/config 落盘，后续批收尾回归按新取值分流
