## Deliverables

```yaml
- path: __init__.py
  kind: reference   # 删除目标：本 change 的交付物是「删除该文件」这一动作本身；reference 语义下不参与缺件硬校验（modify 会因实现分支已删而误判缺件）
- path: tests/conftest.py
  kind: modify
- path: tests/test_import_isolation.py
  kind: new
- path: tests/test_config.py
  kind: modify
- path: tests/test_spec_scheduling.py
  kind: modify
```

## 1. 根除包标记

- [x] 1.1 删除仓库根 `__init__.py`（`git rm __init__.py`），确认仓库根不再含包标记
- [x] 1.2 删除后校验导入解析：在仓库根执行 `python3 -c "import fenixd; print(fenixd.__file__); print(hasattr(fenixd,'FenixDaemon'))"`，输出路径须以 `fenixd.py` 结尾且 `hasattr` 为 `True`
- [x] 1.3 生产零影响复核：`grep -rn "^import fenixd\|from fenixd import\|python3 -m fenixd" core/ bin/` 无命中（生产不依赖 `import fenixd`）

## 2. 收集期导入守卫

- [x] 2.1 在 `tests/conftest.py` 的 `sys.path` 规范化（`sys.path.insert(0, project_root)`）之后，加入模块级收集期守卫：`import fenixd` 后断言 `Path(fenixd.__file__).name == "fenixd.py"` 或 `hasattr(fenixd, "FenixDaemon")`，否则 `raise ImportError`，错误信息指明「import fenixd 被同名包截胡（仓库根 __init__.py）」
- [x] 2.2 守卫置于 `sys.path` 规范化之后、其余测试导入之前，确保收集阶段即执行
- [x] 2.3 手动复现验证守卫：临时 `touch __init__.py` 于仓库根 → 运行 `python3 -m pytest tests/test_import_isolation.py -x` 须在收集阶段显式报错且信息指明撞包 → `rm __init__.py` 复原

## 3. 回归锚点

- [x] 3.1 新增 `tests/test_import_isolation.py`，至少断言三项：仓库根 `__init__.py` 不存在；`import fenixd` 的 `Path(fenixd.__file__).name == "fenixd.py"`；模块具备 `FenixDaemon`

## 4. 导入方式收敛

- [x] 4.1 改写 `tests/test_config.py` 中 `TestDaemonSingletonFlock` 的类注释：删除「仓库根 __init__.py 使 import fenixd 解析到同名包」的归因，陈述真实且仍成立的理由——以独立模块名 `fenixd_daemon_under_test` 直载、不注册进 `sys.modules['fenixd']`，避免与其他测试互扰；加载方式保持 `importlib.util` 直载不变
- [x] 4.2 改写 `tests/test_spec_scheduling.py` 中 `setUpClass` 处注释（现「按绝对路径直载 fenixd.py（tests/test_config.py 同款处方）…截胡…故不使用」）：同 4.1，理由改为模块隔离；加载方式不变
- [x] 4.3 复核三处模块级 `import fenixd` 站点（`tests/test_daemon_lifecycle_races.py`、`tests/test_impl_wip_checkpoint.py`、`tests/test_interrupt_recovery_preserve.py`）删除根 `__init__.py` 后即为自然正确写法，无需回退为函数内延迟 import；如有过时注释一并清理

## 5. 全量验证

- [ ] 5.1 运行全量 `python3 -m pytest tests/ -q`，结果须全绿（基线 2651 passed，不得引入新失败）
- [ ] 5.2 复核导入收敛无遗漏：`grep -rn "import fenixd" tests/` 遍历每处，确认各站点导入方式与注释理由均当前成立
