## Deliverables

```yaml
- path: pytest.ini
  kind: new
- path: tests/conftest.py
  kind: modify
- path: tests/timeout-allowlist.yaml
  kind: new
- path: tests/test_timeout_gate.py
  kind: new
```

## 1. 超时硬门

- [x] 1.1 新建 `pytest.ini`：`timeout = 10`、`timeout_method = signal`，附注释说明「仓级单源：凡以本仓为根的 pytest 入口（回归/验证链/本地）自动生效」
- [x] 1.2 `tests/test_timeout_gate.py` 用 pytester 内联样例验证门行为：内层会话显式 `-o timeout=2`（外层用例自身受全局 10s 门约束，样例不得真等 15s），临时目录生成 `time.sleep(3)` 用例 → 断言判 FAILED、失败信息含 `Timeout` 标识与阈值秒数、同会话其余用例继续执行（不向常驻套件引入慢用例）

## 2. 豁免清单与校验

- [x] 2.1 新建 `tests/timeout-allowlist.yaml`（schema：每条 `nodeid`/`timeout_seconds`/`reason`，初始可为空清单但保留 schema 注释示例）
- [x] 2.2 `tests/conftest.py` 增加 `pytest_collection_modifyitems` 钩子：按 nodeid 匹配清单条目注入 `pytest.mark.timeout(timeout_seconds)`
- [x] 2.3 `tests/test_timeout_gate.py` 增加清单校验用例：`reason` 缺失/为空、`timeout_seconds ≤ 0`、YAML 非法 → 校验用例失败并指出违规条目
- [x] 2.4 用 pytester 样例验证清单生效路径（样例项目内联同构 conftest 钩子与样例清单——真实 conftest 的清单路径指向仓库 `tests/timeout-allowlist.yaml`，pytester 临时项目命中不了）：内层默认阈值 1s（`-o timeout=1`），登记 `timeout_seconds: 2` 的慢用例（`sleep(3)`）在 1s 时被判放行、2s 时判超时，对照未登记用例 1s 即超时（数字取门内可执行的小尺度，理由同 1.2）

## 3. 存量处置与全量验证

- [x] 3.1 在 10s 门下全量执行存量套件，收集所有超时用例清单
- [x] 3.2 逐个处置：可修复的替身/测试直接修复（如真自旋改假时钟）；确需更久的登记豁免清单并写明理由
- [x] 3.3 处置后全量回归通过，报告无 timeout 失败
