# code-fix 选批亲和性聚类与回归两段式

<!-- knowledge: capability=codefix-affinity-batching rev=2
     sources=spec/archive/2026-10-04-add-codefix-affinity-batching,spec/archive/2026-10-06-evo-add-codefix-test-targets-fallback-sanitization -->

code-fix 车道的选批算法与批收尾回归分流：选批按文件亲和性贪心装箱（同文件条目永同批），批内并行波次上限随批规模自适应，批收尾回归按「链内是否末批」两段式（中间批定向、末批全量兜底）。

## 规则

### 选批：文件亲和性贪心装箱
- 选批以**文件组**为最小不可拆单元：按条目 `file` 字段把 open 条目归并成组，同文件全部条目必入同批，MUST NOT 为凑批规模拆散文件组。
- 目标规模 T = `admin.code_review_fix.batch_size`（缺省 20，语义为「目标规模」而非精确条数）；硬上限 H = 2×T。
- 组间排序按组内最早 `first_seen_at` 升序（缺失回退组内最小 `item_id`），组内条目保持稳定序；装箱确定性，同输入必同输出。
- 装箱吸收规则：
  - 「同目录」取直接父目录全等（无父目录的顶层文件互不同目录），不引入模块/语义相似度判据；
  - 同目录组浮动吸收：加入后批条数 ≤ H 即可（允许超过 T）；
  - 异目录组仅当前批条数 < T 时吸收，吸收后批条数 ≥ T 即封批；
  - 批条数达 H 封批，余组进下一装箱批；
  - 单文件组自身条数 > H 时独立成批、不拆分（整批可超 H）。
- 排除口径：失败档案条目并集 ∪ `exclude_ids`（chain_skipped）不入选；台账读失败返回空列表（fail-closed）。
- 选批每次调用返回装箱后的首批；链逐批推进、每轮重新选批，无需一次返回全部批。

### 批内并行波次上限自适应
- 批内子代理并发上限随批内文件组数 G 分档：G ≤ 4 → 上限 4；5 ≤ G ≤ 8 → 上限 6；G ≥ 9 → 上限 8。8 为硬上限（防网关限流放大），任何批规模 MUST NOT 超过；4 为下限（单文件大组批不因批条数变大上调）。
- 上限值由 prompt 组装点（`_build_code_fix_prompt`）按批内文件组数计算，经 `{wave_cap}` 占位符注入 `agents/code-fix.md` 派发节；模板缺占位符时回退 4。
- 串行/并行判定（仅 1 个文件组或总条目 ≤2 不派子代理）由批内并行协议承载，见 [code-fix-batch-parallel](code-fix-batch-parallel.md)。

### 批收尾回归两段式
- 链末批判定与链选批同口径：按失败档案 ∪ `chain_skipped` ∪ 延迟台账排除后、再排除本批 item_ids，无剩余可选批条目（与选批返回空同判据）→ 本批为末批。MUST NOT 用不排除上述条目的裸 `count_open_items` 判定——链实际收敛的最后一批收尾时常有此类被排除 open 条目在档，裸计数会把末批判成非末批、走定向回归后链随即正常收敛，全量兜底整链落空。判定必须在核销前做（核销会改变 open 集）。
- 末批恒走全量回归（verify.yaml regression 段原样执行），作为链收尾的合并防线；MUST NOT 末批定向。
- 非末批：`admin.code_review_fix.targeted_regression` 为 true（缺省）、`regression.cmd` 含 `{test_targets}` 占位符、且触碰面映射非空，三条件同时成立走**定向回归**；任一不满足回退全量。fail-open 哲学：定向化是优化不是门槛，任何不确定都回退「多花回归时间」一侧，MUST NOT 回退到跳过回归；映射空集回退时记日志留痕。
- `{test_targets}` 占位符声明在 verify.yaml `regression.cmd` 中，框架替换为空格连接的测试路径列表（路径做 shell 引用包裹），同值导出 `FENIX_TEST_TARGETS` 环境变量（双轨）；str/list 两态 cmd 都支持，list 形态仅替换元素级占位符。cmd 无占位符 = 该项目不参与定向化，恒全量，存量项目零迁移。
- 触碰面映射（纯函数，输入为本批产物 `fixed` 行的 `file` 集合）：测试文件（`tests/` 下或 `test_` 前缀/`_test` 后缀）直接入选；产品文件按「同目录 `tests/` 的 `test_<stem>.py` 命名匹配」∪「`tests/` 树内 import 该模块的文件」（单次 `grep -rl` 反查，MUST NOT 逐文件 Python 遍历）取并集；路径相对回归执行根（worktree）解析。
- 定向回归复用 `run_regression` 既有机制（主机级套件锁、JUnit XML 解析、`timeout_seconds` 硬超时全继承），只缩小测试集、不新增执行通道。进度文案区分「定向回归」与「全量回归」。
- 回退出口与定向重试轮的 `{test_targets}` 占位符消毒契约见 [codefix-test-targets-sanitization](codefix-test-targets-sanitization.md)。
- 失败语义同轨：定向回归失败与末批全量失败均走回归失败处置路径（定向重试轮，见 [code-fix-lane](code-fix-lane.md)），MUST NOT 为定向失败另设处置分支。

### 配置键 targeted_regression
- `admin.code_review_fix.targeted_regression`：批收尾回归两段式开关，严格 bool，缺省 true；非法值回退缺省并记 warning，不抛异常、不中断批链。参数定义、读写校验与设置页开关见 [code-fix-config](code-fix-config.md)。

## 溯源

- 2026-10-04 2026-10-04-add-codefix-affinity-batching（spec/archive/2026-10-04-add-codefix-affinity-batching） — 新建本页：选批由时间序截前 N 改为文件组不可拆贪心装箱（batch_size 放宽为目标规模 T、硬上限 H=2T、同目录=直接父目录全等）；波次上限由模板固定常量改为按组数分档注入（4/6/8）；批收尾回归两段式（末批恒全量兜底、非末批 `{test_targets}` 定向、fail-open 回退全量）；新增 targeted_regression 配置键与设置页开关。
- 2026-10-06 evo-add-codefix-test-targets-fallback-sanitization（spec/archive/2026-10-06-evo-add-codefix-test-targets-fallback-sanitization） — 追加交叉引用：回退出口与定向重试轮的占位符消毒契约拆分至 codefix-test-targets-sanitization 页
