## ADDED Requirements

### Requirement: 仓库根不再是包

仓库根 MUST NOT 含 `__init__.py`（或任何使 `/root/fenixd` 被解析为同名包 `fenixd` 的包标记），以保证 `import fenixd` 在任一 `sys.path` 顺序下均解析到守护脚本模块 `fenixd.py` 而非同名空包。

#### Scenario: 根包标记缺失

- **WHEN** 检查仓库根 `<repo_root>/__init__.py`
- **THEN** 该文件不存在

#### Scenario: import 解析到守护模块

- **WHEN** 在仓库根（`sys.path` 含仓库根）执行 `python3 -c "import fenixd; print(fenixd.__file__); print(hasattr(fenixd, 'FenixDaemon'))"`
- **THEN** 输出路径以 `fenixd.py` 结尾，`hasattr` 为 `True`

#### Scenario: 自举部署镜像无悬空链接

- **WHEN** 检查 `.fenix/__init__.py`（若存在）
- **THEN** 不指向已删除的仓库根 `__init__.py`（悬空符号链接 MUST 清除）

### Requirement: 收集期导入守卫

`tests/conftest.py` MUST 在收集期断言 `import fenixd` 绑定的是守护脚本模块（`__file__` basename 为 `fenixd.py`，或模块具备 `FenixDaemon`）。一旦被同名包截胡，MUST 以显式硬失败终止收集，禁止降级为下游测试函数执行期的静默 `AttributeError`。

#### Scenario: 撞包时收集期硬失败

- **WHEN** 人为在仓库根放置 `__init__.py`（复现截胡条件）后运行任一测试文件
- **THEN** pytest 在收集阶段即显式报错退出，错误信息指明 `import fenixd` 被同名包截胡，且失败早于任何测试函数执行

#### Scenario: 正常态守卫静默放行

- **WHEN** 仓库根无 `__init__.py` 时运行全量 pytest
- **THEN** 守卫不产生任何报错，测试照常收集执行

### Requirement: 导入方式收敛

各测试对 `fenixd` 的导入方式 MUST 保留一条清晰且当前成立的理由：纯为规避截胡而存在的 workaround MUST 随根因消除而移除或改写为自然导入；因模块隔离（不污染 `sys.modules['fenixd']`）而保留的绝对路径直载 MUST 更新注释，删除已失效的截胡归因。未跟踪的探针残留文件 MUST 删除。

#### Scenario: 探针残留清除

- **WHEN** 检查 `tests/test_import_probe2.py`
- **THEN** 该文件不存在

#### Scenario: 保留的直载注释准确

- **WHEN** 检查 `tests/test_config.py`、`tests/test_spec_scheduling.py` 中 `importlib.util` 直载 `fenixd.py` 处附近的注释
- **THEN** 注释陈述的理由为模块隔离（不污染 `sys.modules['fenixd']`），不再归因于已消除的仓库根 `__init__.py` 截胡

#### Scenario: 模块级 import 站点为自然写法

- **WHEN** 检查 `tests/test_daemon_lifecycle_races.py`、`tests/test_impl_wip_checkpoint.py`、`tests/test_interrupt_recovery_preserve.py` 的 `import fenixd`
- **THEN** 均为模块级导入，且删除根 `__init__.py` 后无需任何 workaround 即可正确绑定守护模块

### Requirement: 回归锚点

MUST 存在一条专属回归测试，断言仓库根包标记缺失与 `fenixd` 模块身份，使该缺陷在任何后续改动中复发时于测试层立即暴露。

#### Scenario: 回归测试在场且通过

- **WHEN** 运行 `tests/test_import_isolation.py`
- **THEN** 断言仓库根 `__init__.py` 不存在、`import fenixd` 的 `__file__` basename 为 `fenixd.py`、模块具备 `FenixDaemon`，全部通过
