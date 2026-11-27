# Tasks: fix-windows-review-longtail

> 执行纪律：TDD（任务组 1 测试先行）；Linux 零变化硬约束；win32 触点全部为日志/
> 解码/preflight 路径（过机豁免声明见 design D9）；每任务组收口跑宿主 pytest。

## 1. pytest 先行（纯逻辑层覆盖）

- [x] 1.1 `tests/test_platform_pal.py` 新增：win32 解码冒烟（GBK 字节序列喂
  `subprocess.run` 解码路径不抛）；`fenix-init`（仓库根）preflight 缺模板 → 退出非 0
  且工作目录无新文件（tmp_path 隔离）；`--version` 退出 0 有输出；
  `FENIX_LINKS` 断言不含 `__init__.py`
- [x] 1.2 宿主全量回归基线：`tests/test_platform_pal.py` + `tests/test_platform_guard.py`
  + `tests/test_dashboard_orphan_guard.py` 全绿（改动前快照）

## 2. win32 告警分级（D1）

- [x] 2.1 `core/platform/win32.py` `install_unit`：`_service_state` None 且无 sc 失败
  证据 → debug 级/静默；保留「有瞬时失败证据」路径的 warning
- [x] 2.2 返回 JSON 形状不变（ok/error/already/unit）

## 3. win32 解码加固与日志编码安全（D2/D3）

- [x] 3.1 `core/platform/win32.py` 全部 `capture_output` 调用点补
  `text=True, encoding="utf-8", errors="replace"`
- [x] 3.2 平台 logger stderr handler errors=replace 包装（Linux handler 不动）

## 4. fenix-init preflight / --version / 骨架清单（D4/D5/D6）

- [x] 4.1 `fenix-init`（仓库根脚本）：main() 首步全读面校验（缺失 exit 2 + 明细，先于任何 mkdir）
- [x] 4.2 render 失败回滚已建目录（不留半成品）
- [x] 4.3 argparse `--version`（读 VERSION，缺失输出 unknown 退出 0）
- [x] 4.4 `FENIX_LINKS` 移除 `__init__.py`

## 5. install.ps1 完整性硬失败（D7）

- [x] 5.1 `install.ps1` 模板/部署面自检缺失 → exit 1 + 缺失清单（去 WARN+exit0 降级）
- [x] 5.2 保留 UTF-8 BOM（PS5.1 GBK 误读防护）

## 6. 8×SKILL.md 注记（D8）

- [x] 6.1 统一注记块插入 8 个 `skills/*/SKILL.md`（首个可复制命令之前）
- [x] 6.2 高频命令行内双写每 skill ≤3 处；语义逐字不变
- [x] 6.3 grep 验收：8/8 文件含注记；`python3` 总数与基线一致（未改写既有命令）

## 7. verdict 收口

- [x] 7.1 宿主全量 0 failed 0 新增豁免（Linux 零变化）
- [x] 7.2 注记 grep 8/8；preflight/version/解码用例全绿
- [x] 7.3 提交：spec 目录 + 实现分开提交，message 引用本 SPEC 名
