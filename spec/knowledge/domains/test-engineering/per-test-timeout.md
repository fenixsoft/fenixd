# pytest 单用例超时硬门

<!-- knowledge: capability=per-test-timeout rev=1
     sources=spec/archive/2026-10-03-add-per-test-timeout-gate -->

本仓 pytest 套件的单用例时长硬门：每个测试用例必须在 10 秒内完成，慢用例被机械判失败，确需更久的走显式豁免清单——慢用例不得静默拖长每一次回归。

## 规则

- 单用例 10s 硬门：每个测试用例 SHALL 在 10 秒内完成，超时判 FAILED，同会话其余用例继续执行。门以仓根 `pytest.ini` 单源声明（`timeout = 10`、`timeout_method = signal`）：凡以本仓为根执行 pytest 的入口（回归车道、spec 验证链、开发者本地、worktree、嵌套 pytester 内层会话）自动生效，任何入口不以命令行参数或逐入口配置重述/旁路该门。
- 全局阈值不提供放宽配置项；唯一放宽通道是显式豁免清单。
- 中断方法固定 signal（SIGALRM）：只中断主线程，超时判失败后会话继续；thread 方法超时会 dump 栈后 `os._exit` 整个 pytest 进程（一次慢用例杀掉整场回归），禁用作全局方法。SIGALRM 无法中断 C 扩展深处的阻塞——此类用例的处置是拆分/改造用例或登记更长时限豁免，不是切换全局方法。
- 超时失败信息含机读标识 `Timeout (>Ns) from pytest-timeout`（N 为阈值秒数），回归读侧与人工据此区分「超时失败」与「断言失败」；junit XML 中超时是普通 failure，回归读侧按普通失败消费、无超时专项识别。

### 显式豁免清单

- 豁免落盘 `tests/timeout-allowlist.yaml`，每条三字段必填：`nodeid`（与 `pytest --collect-only -q` 输出逐字一致，参数化用例含 `[参数]` 后缀）、`timeout_seconds`（>0）、`reason`（写明等什么/等多长，缺失或为空即违规）。
- `tests/conftest.py` 的 `pytest_collection_modifyitems` 在收集期按 nodeid 逐字匹配清单条目，命中即注入 `pytest.mark.timeout(N)` 覆盖全局阈值；未登记用例恒按 10s 判定。
- 清单由 `tests/test_timeout_gate.py` 机械校验：`reason` 缺失/为空、`timeout_seconds ≤ 0`、`nodeid` 缺失、条目非映射、YAML 解析失败均判测试失败并指出违规条目（序号 + 字段）——豁免必须显式留痕，禁止静默放宽。清单文件缺失按空清单处理；YAML 非法时加载报错、校验用例失败。
- 仓库真实清单须常净：schema 校验零违规是常驻回归项。

### 全量套件零隐性超时

- 全量回归在 10s 门下通过且报告中零因超时判失败的用例；套件中不存在依赖隐性超时的慢用例——确需超过 10s 的用例必须登记豁免，未登记的慢用例即门下失败。
- 新增用例过慢即被门当场拦截，处置二选一：修复替身/测试（如真自旋改假时钟），或登记豁免并写明理由。

### 门行为的验证方式

- 门行为与清单生效路径用 pytester 内联样例验证，不向常驻套件引入慢用例（否则门自身会拦它）。
- 样例约束：外层验证用例自身受同一 10s 门，样例 sleep 时长取门内小尺度，不得照搬全局阈值数字真等 15s/30s；内层会话 MUST 显式 `-o timeout=<小值>` 压低阈值——pytester 临时目录落在仓内 basetemp，内层 pytest 向上发现仓根 `pytest.ini` 会继承 10s 门，显式 `-o` 是唯一可靠控制；样例项目内放最小 `pytest.ini` 钉住 rootdir，内层节点 ID 才相对样例项目、清单 nodeid 才能逐字对上；清单生效路径的样例项目内联同构 conftest 钩子与样例清单（真实 conftest 的清单路径指向仓库 `tests/timeout-allowlist.yaml`，pytester 临时项目命中不了）。

## 溯源

- 2026-10-03 add-per-test-timeout-gate（spec/archive/2026-10-03-add-per-test-timeout-gate） — 新建本页：仓级 pytest.ini 10s 单用例硬门（signal 方法、无全局放宽旋钮）、显式豁免清单（三字段 schema + conftest 收集期注入 + 机械校验）、全量套件零隐性超时不变式、pytester 门内小尺度验证样板（显式 -o 压阈值 + 最小 ini 钉 rootdir）。
