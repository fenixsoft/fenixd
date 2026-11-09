## Deliverables

```yaml
- path: core/git_env.py
  kind: new
- path: core/pm_engine/engine.py
  kind: modify
- path: core/systemd_hosting.py
  kind: modify
- path: bin/migrate_to_systemd.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_git_env.py
  kind: new
- path: tests/test_push_retry_recovery.py
  kind: new
- path: tests/test_spec_approve_push.py
  kind: modify
- path: tests/test_systemd_env_path_hygiene.py
  kind: modify
```

## 1. git 环境单源解析器

- [ ] 1.1 新建 `core/git_env.py`：`resolve_git_env(config)` 单源解析——HOME 依次取进程 env 非空 `HOME` → `pwd.getpwuid(os.getuid()).pw_dir` → 配置 `pm.push.credential_home`；产出结构含 resolved_home、process_env（含 HOME 注入版 env 拷贝）、credential_file 路径（默认 resolved_home 下 `.git-credentials`，`pm.push.credential_file` 覆盖）；三级皆空返回无 HOME env 不抛异常；配置显式置空 `pm.push.credential_file` 关断 helper 兜底（credential_file 为 None）
- [ ] 1.2 新建 `tests/test_git_env.py`：覆盖 env 有 HOME 直取、无 HOME 走 pwd、pwd 失败走配置覆盖、三级全空安全回退不抛异常、credential_file 显式覆盖与置空关断、解析路径不存在时不产生假路径

## 2. 推送子进程凭证双腿

- [ ] 2.1 `core/pm_engine/engine.py` `_git_push_ref`：以 `resolve_git_env` 产出 env 显式传入 `subprocess.run(env=…)`；凭证文件在场时命令追加 credential helper 参数——argv 单元素 `["-c", f"credential.helper=store --file={abs}"]`，MUST NOT 拆多元素（拆开后 `--file=` 成 git 顶层未知选项，推送必败）（经 config 读 `pm.push.credential_file`），文件缺席不追加参数；解析失败安全回退现状行为并记 WARNING 日志
- [ ] 2.2 扩展 `tests/test_spec_approve_push.py` 或新建用例于 `tests/test_push_retry_recovery.py`：daemon env 无 HOME 时子进程 env 含注入 HOME、凭证文件在场时命令含 helper 参数、缺席时不含、注入失败回退不中断推送

## 3. 承载层 HOME 基线

- [ ] 3.1 `core/systemd_hosting.py`：`capture_env_candidate` 对候选稿做 HOME 基线检查（经 `resolve_git_env` 单源取值），缺失补 `HOME=<resolved>` 并按 PATH 追加同款注释留痕；已含非空 HOME 时产物逐字节不变；`render_project_unit` 增加保底行 `Environment=HOME=<resolved>`（env 文件在场含 HOME 时照常覆盖，systemd 加载顺序语义不变）
- [ ] 3.2 `bin/migrate_to_systemd.py`：迁移 plan 摘要输出 HOME 卫生结论行（「完整」或「补齐 <值>」），与既有 PATH 卫生结论并列
- [ ] 3.3 扩展 `tests/test_systemd_env_path_hygiene.py`：候选稿缺 HOME 补齐留痕、已含 HOME 产物逐字节不变、unit 保底行存在且 env 文件覆盖语义不变、迁移摘要 HOME 结论行

## 4. 启动凭证自检

- [ ] 4.1 `fenixd.py` 启动自检链新增凭证探测：解析 HOME 目录存在性、凭证文件在场性、remote URL 内嵌凭证扫描（纯本地不网络探测；探测对象＝daemon 自身仓库与全部已接管项目的 remote URL 集，`git config --get-all remote.*.url` 本地读取，任一 URL 含凭证即认 URL 腿在场）；双腿皆缺或 HOME 解析失败发 WARNING 告警（含人工处置指引），探测异常 fail-open 仅记日志不阻断启动
- [ ] 4.2 于 `tests/test_push_retry_recovery.py` 增用例：双腿皆缺告警一次、单腿可用不告警、探测异常不抛出不阻断

## 5. done 态退避续推通道

- [ ] 5.1 `core/event_bus.py` `_recover_one` 增加 done 分支：status==done 且非退避期（`_is_push_backoffed` False）且 `_get_push_retry_count < pm.push.max_retries` 且非耗尽升级终局（error 文本 `[push_failed` 标记或计数达上限，任一命中跳过；不查 admin store）时经 admin executor 非阻塞投递 `pm_engine.approve_push`——executor 由 fenixd.py 启动序列事后挂载到 event_bus（同 `code_fix_orchestrator` 装配契约），event_bus 侧 `getattr(self, "_admin_executor", None)` fail-open，None（未挂载/`admin.workers=0`）时当轮 WARNING 跳过下轮重判、MUST NOT 内联同步；投递形态对齐 fenixd.py `_check_approve_push_requests`（submit + submitted 计数 + RuntimeError 回滚）；退避/计数读侧复用 `ReportBuilder._is_push_backoffed` / `_get_push_retry_count`（经 pm_engine 静态转发，禁裸解析 error 文本）；退避期内 debug 级跳过；投递拒绝/异常按既有车道口径降级不中断整轮扫描；复用 approve_push 既有单飞锁/幂等/SHA 去重，不新增推送语义与内存定时器
- [ ] 5.2 新建 `tests/test_push_retry_recovery.py`：退避到期续推投递发生、退避期内 debug 跳过不发 push、计数达上限/push_failed 已发不再投递、重启后（STATE 字段存量+退避已过期）首轮扫描拾取、executor 拒绝时扫描不中断、executor 缺席（None）当轮 WARNING 跳过且无内联 approve_push 调用、多 spec 命中时主循环不内联阻塞

## 6. 收口冒烟

- [ ] 6.1 全量跑本 SPEC 相关测试（test_git_env / test_push_retry_recovery / test_systemd_env_path_hygiene / test_spec_approve_push / test_systemd_hosting）全绿；`python3 -c "import fenixd, core.event_bus, core.pm_engine.engine, core.systemd_hosting, core.git_env"` 冒烟导入通过
