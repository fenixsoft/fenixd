# Tasks: fix-windows-service-userprofile

## Deliverables

```yaml
- path: core/platform/win32.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: docs/install.md
  kind: modify
- path: tests/test_install_unit_env.py
  kind: modify
- path: tests/test_config_user_dir_env.py
  kind: new
- path: tests/integration/windows/g1_full_parity_checklist.md
  kind: modify
```

## 1. install_unit 默认 USERPROFILE 注入

- [x] 1.1 core/platform/win32.py `install_unit`（L1706 起）：`env=None` 时默认并入安装调用者 `USERPROFILE`（安装时刻解析：`os.environ.get("USERPROFILE")` 与 `Path.home()` 双读，取非 systemprofile 侧为锚；两读一致指向 systemprofile 或均无值时跳过注入并在返回 JSON 附 `userprofile_skip` 提示字段，不 fail 安装）；**LocalSystem 守卫**（评审修补）：already 路径先读服务账户（`sc qc` 的 ObjectName/StartName），非 LocalSystem 专用账户跳过默认注入（SCM 已提供该账户真实 profile，注入安装者 profile 反成覆写）并附 `userprofile_skip` 提示；新装路径无既存服务、NSSM 默认 LocalSystem，恒注入；显式 `env` 同名键以显式值优先（守卫不约束显式传入）；REG_MULTI_SZ read-modify-write 合并语义不变；docstring 同步新语义
- [x] 1.2 tests/test_install_unit_env.py：新增缺省调用注入 USERPROFILE（含既有条目保留断言）、显式 env 覆盖默认、解析失败跳过三态用例；更新锁定旧行为（env=None 不注入）的存量断言
- [x] 1.3 运行 `python3 -m pytest tests/test_install_unit_env.py tests/test_platform_pal.py -q` 全绿

## 2. FENIX_HOME 覆盖单源

- [x] 2.1 core/config.py L20：`USER_CONFIG_DIR` 按 `FENIX_HOME` 解析（设了 `FENIX_HOME` → `Path(FENIX_HOME) / ".fenix"`；未设 → 现状 `Path.home() / ".fenix"`）；注释注明「FENIX_HOME 语义 = home 替代」与单源纪律
- [x] 2.2 新增 tests/test_config_user_dir_env.py：FENIX_HOME 设置/未设两态解析断言 + 门面 `core.dashboard.data.USER_CONFIG_PATH` 派生跟随断言（importlib 环境隔离，防进程内其他测试串扰）
- [x] 2.3 全库核对无旁路推导：grep 确认消费点均经 `core.config.USER_CONFIG_DIR`/门面派生，无独立 `Path.home()` 拼 `.fenix` 的旁路（dashboard data 组经 `_facade.USER_CONFIG_PATH` 属合规）

## 3. 设置页提示携带解析路径

- [x] 3.1 core/dashboard/data/config_admin.py 后端补齐 `/api/config` payload `path` 字段（评审实测：read_config L895 payload 现无 `path` 键，原主张「user scope 已有」系误引 L3382/3396 的 sync 错误返回字段——user/project 两 scope 都须补）：user scope 取 `str(config_path)`（read_config L914-916 已解析，`raw_exists=False` 早退路径 L923-924 同样携带），project scope 取项目配置解析路径（read_effective_config 约 L1083-1112，异常早退与正常路径形状一致），避免前端二次推导
- [x] 3.2 core/dashboard/static/src/pages/settings/index.tsx L612-617：`!raw_exists` 提示在两 scope 文案后追加实际解析路径（`config.path`），样式与既有 warning 提示一致
- [x] 3.3 core/dashboard/static 下 `pnpm build` 重建 dist 通过，构建产物随分支提交（pnpm build 重建通过、产物经 bundle 核对含新文案；本轮复核：build exit=0，dist/p__settings__index.573d6b70.async.js 含 \uXXXX 转义形态新文案；以本地构建通过替代入库提交——dist/ 不入库系 .gitignore 2026-09-04 仓库决策「构建产物不入库，merge 后框架自动重建主树产物」，入库曾是 merge 产物冲突事故源，详见 run-result findings 验收偏差条目）

## 4. 文档与清单回填

- [x] 4.1 docs/install.md §8：服务环境注入从"建议"升为必做表述（注明 `pal.install_unit` 已默认注入调用者 USERPROFILE；手工 nssm 路径给出 Set-ItemProperty 注入与 nssm restart 命令；存量部署补救一键命令）；§4a 补一句服务化形态下由 §8 注入保障
- [x] 4.2 docs/install.md 故障排查段：新增「设置页提示配置文件不存在 → 看提示中解析路径 → USERPROFILE 漂移/FENIX_HOME 逃生口」条目

## 5. Windows 过机复验与清单回填

- [x] 5.1 经 SSH win-vm（`ssh -i ~/.ssh/winvm_admin -p 22222 docker@127.0.0.1`，宿主 /root 以 \\host.lan\Data 可达）：以实现分支代码路径跑平台 pytest 子集与 test_install_unit_env.py / test_config_user_dir_env.py，全绿留档
- [x] 5.2 win-vm 内服务注入自举场景实测：以实现分支代码对测试服务执行 `install_unit`（不传 env）→ 断言注册表 AppEnvironmentExtra 含 `USERPROFILE=<真实profile>` 且既有条目保留 → `nssm restart` 后服务侧进程内验证 `Path.home()` 解析正确
- [x] 5.3 tests/integration/windows/g1_full_parity_checklist.md G1-01b（用户级配置自举）按 5.1/5.2 结论回填复验状态与日期
- [x] 5.4 通道中断时按环境止损纪律申报 partial + unattainable（附 SSH 失败证据），Linux 逻辑面照常交付；通道恢复路径写入 run 结果文件
