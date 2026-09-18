## Context

`.fenix/verify-serving/` 是 static_scope=worktree / command 型验证契约的
serving worktree 存放根（`core/pm_engine/verification/serving.py`
`_ensure_serving_worktree`）。每个 serving worktree 是 `git worktree add --detach`
出的完整仓库副本，并（默认 `prefer-offline`）实装一份 node_modules。

现状两条泄漏路径：

- **默认依赖模式 `prefer-offline` 每份实装 1.6G**：实测 19 个 worktree
  各 1.6G，`node_modules` inode 互不相同、link count=1（真拷贝）。代码里
  `hardlink` 模式（`os.link` 硬链接副本，秒级共享 inode）已实现但非默认。
- **目录无生命周期回收**：`_evict_spec_serving` 只在 spec→done 事件触发，
  且 `wt_path` 取自仅存内存的 `_contract_static_servers` 缓存。daemon 重启
  清空缓存 / spec 未经 done 消失（archive、手动清理、状态回退）→ 目录永久
  残留。实测 19 个中 15 个对应 spec 已从 changes 与 archive 双双消失。
  `serving_registry.sweep`（600s 节拍 + 启动）只收割**进程与登记项**，
  不删目录。`worktree_manager.cleanup_stale_worktrees` 只管
  `worktree.base_dir`（默认 `.claude/worktrees`），不覆盖 `.fenix/verify-serving`。

约束：清扫是破坏性删除；worktree 内的验证可能有并发创建；主树对实现 Agent
只读（`.fenix/` 为运行时文件，属 reference 非交付物）。

## Goals / Non-Goals

**Goals**

- 存量无主 serving worktree 与 boot.log 可被确定性回收（启动 + 周期两触发点）。
- 新默认（hardlink）使单份 worktree 占用从 1.6G 降到 ~24M。
- 清扫 fail-safe：证据不足一律保留，绝不误删在飞验证的工作区。

**Non-Goals**

- 不改 `serving_registry.sweep` 的进程/登记收割语义（本次叠加目录维度）。
- 不由 SPEC 交付「删除主树既有 30G 存量」（worktree 隔离 + 主树只读），
  存量人工清理，登记 `.fenix/todo.md`。
- 不做 node_modules 的跨 worktree 内容去重（hardlink 已解决）。

## Decisions

### D1：保留集判据（三重 + 宽限），fail-safe

保留条件（满足其一即保留）：

1. **spec 存活**：目录名按 `{spec}-{10 位时间戳}` 解析出 spec，且
   `spec/changes/<spec>` 或 `spec/archive/*-<spec>` 存在。
2. **登记在册**：目录绝对路径 ∈ `servers.json` 任一条目 `worktree` 字段。
3. **活进程**：`/proc` 扫描有进程 argv 或 cwd 指向该目录。
4. **宽限期**：目录 mtime 在宽限期内（模块常量 `RECLAIM_GRACE_SECONDS = 600`，
   与 600s 清扫节拍同量级、不小于单次 worktree 创建 + 依赖供给时长；**不新增
   配置键**——`admin.escalation_cooldown_minutes` 语义为管理员升级静默期
   （`core/config.py`，测试 `tests/test_config.py:145` 断言缺省 60 分钟），与目录
   宽限无关，不复用）。

四个 helper 均须**只读**且**异常时返回「保留」**（保守侧）：

- 名解析复用 `_spec_from_worktree_name` 同款规则（`rsplit("-",1)` 且末段
  `.isdigit()` 且恰 10 位），但**必须校验末段长度为 10**——否则
  `evo-...-575976-1789694112` 会被误当作 spec=`...-575976`（正确）与
  末段=`1789694112`（正确）没问题，但 `add-foo-123`（非时间戳）会被误解析。
  10 位数字是既有时戳约定，显式校验。
- archive 匹配需按 `*-<spec>` 后缀匹配（archive 目录名带日期前缀）。
- 判据 2 的路径比较 MUST 先 `Path.resolve()` 再**全等**匹配，且 `worktree` 为
  空串的登记项 MUST NOT 参与匹配（`serving_registry.register` 在未传 `wt_path`
  时写 `""`，见 `core/serving_registry.py:118`；`serving.py:346` 与
  `serving.py:771` 两处调用即不传）——否则「空串包含」或相对/绝对路径不一致会
  把在飞实例误判为未登记。

**实测校准（2026-09-18）**：当前 `.fenix/verify-serving/` 下 19 个目录中，18 个
的 spec 仍可解析存活（15 个命中 `spec/archive/2026-09-*`、3 个在 `spec/changes/`），
仅 `verify-draft-fixture-1788860224` 无主。故判据 1 的「归档等同存活」意味着启动
reconcile 对**存量**只回收约 1 个目录，存量 30G 主体（18 × 1.6G）由人工清理承担
（Non-Goals）；本 SPEC 的自动机制主要治理**增量**泄漏，减小增量占用靠 D6 的
hardlink 默认（1.6G → ~24M）。

**Alternatives considered**：
- 「按 mtime 陈旧度删」——被否：在飞验证可能长时间无文件变动，mtime 不可靠
  （与 fix-orphan-ready-recovery-liveness 同类教训）。
- 「只看 spec 存活」——不安全：spec 刚被 remove 但验证仍在跑的瞬间会误删。

### D2：清扫执行器复用 `_remove_serving_worktree`

回收动作直接调既有 `pipeline._remove_serving_worktree(wt_path)`（已实现
`git worktree remove --force` + `prune`，幂等）。清扫器**不重新实现 git 调用**，
仅负责「枚举 → 判据 → 调 remove」。为让清扫器不依赖 pipeline 实例，
新增一个模块级 `reclaim_verify_serving(project_root, logger, in_flight=None)`
返回回收计数，内部直接内联 git 调用（与 `_remove_serving_worktree` 同款），
避免为了拿 pipeline 而构造整个 VerificationPipeline。

### D3：清扫器落位 `core/pm_engine/verification/serving_reclaim.py`

- 与 `serving.py` 同目录（验证域），避免 core/ 顶层再膨胀。
- 导出单一入口 `reclaim_verify_serving(project_root, logger, is_spec_in_flight=None) -> dict`
  返回 `{"reclaimed": [...], "kept": [...], "boot_logs_reclaimed": [...]}`。
- 纯文件系统 + 子进程，无 LLM/网络。

### D4：触发点接线在 `fenixd.py`

- **启动**：`_sweep_verify_serving_registry(use_in_flight=False)` 之后追加
  `self._reclaim_verify_serving_tree(use_in_flight=False)`。
- **周期**：`orphan_clean_ts` 600s 节拍内，在既有 `_sweep_verify_serving_registry()`
  之后追加 `self._reclaim_verify_serving_tree()`。
- 两处均 try/except 包裹，异常记 ERROR 不中断主循环（与既有 sweep 一致）。

**Alternatives considered**：
- 「只在 done 时清扫」（用户提问）——不够：done 只覆盖正常终局，覆盖不了
  daemon 重启/崩溃/archive 绕过 done 的路径，而实测泄漏主体（30G）正是这类。
  done 时仍是「清扫现场」（`_evict_spec_serving` 负责当轮那个），但**不可作
  唯一机制**。故 done 路径保留，另加启动 + 周期两条按无主判据的回收。

### D5：boot.log 同批回收

`<spec>-boot.log` 与目录同根同源。按同一「spec 存活」判据回收：spec 不在
changes/archive 且无在飞 run → 删。`contract_selfcheck.json`、顶层状态文件、
无法解析名者一律保留。

### D6：默认值改动的最小一致面

`DEFAULT_DEPS_MODE = "hardlink"`（`core/verify_contract.py`）+ 三处显式
镜像默认值保持同步：

- `.fenix/config.template.yaml` 的 `verify` 段补 `deps_mode: hardlink`。
- `core/dashboard/data/config_admin.py` 两处缺省字典 `{"deps_mode": ...}`。
- `VerifyPanel.tsx` 缺省选中值 + 「默认」标注移到 hardlink。
- 测试断言（`resolve_deps_mode(None, None) == DEFAULT_DEPS_MODE` 等）。

`resolve_deps_mode` 优先级链不变，仅兜底字面量变。

## Risks / Trade-offs

- **[误删在飞 worktree]** → D1 四判据 + 宽限期 + 异常返回保留；删除前重新
  校验活进程（清扫器内串行，无 TOCTOU 窗口以外的假设）。
- **[archive 按后缀匹配误命中同名 spec]** → 匹配 `*-<spec>` 全等后缀
  （与 `_spec_from_branch` 既有约定一致），非 glob 前缀（防 spec 互为前缀
  误归属，见 fix-spec-branch-glob-prefix-misattribution）。
- **[hardlink 并发构建穿透共享 inode]** → 已在模块文档与本 SPEC 记录；主树与
  worktree 并发构建属既有约束，默认切 hardlink 后此约束变得更需注意，但
  hardlink 本就是为省空间设计，风险与收益有明确取舍（用户已决策）。
- **[启动 reconcile 拖慢 daemon 启动]** → 清扫为纯文件系统枚举 + 少量 git
  调用，19 条目量级毫秒~秒级，可忽略。
- **[存量 30G 不在本 SPEC 自动回收内]** → 判据 1「归档等同存活」使存量中 18 个
  目录被保留（实测仅 1 个无主可自动回收）；存量清理由 todo.md 承载，本 SPEC 只
  保证新机制生效后不再累积，并把单份增量占用从 1.6G 降到 ~24M（D6）。

## Migration Plan

1. 合入后 daemon 重启：启动 reconcile 自动回收无主存量（15 个无主目录）。
2. 人工执行 `.fenix/todo.md` 登记的存量清理（若启动 reconcile 已清则跳过）。
3. 回滚：`verify.deps_mode: prefer-offline` 可恢复旧默认；清扫器可通过
   config 开关（如 `verify.serving_reclaim.enabled: false`）禁用——若实现期
   决定加开关则同步界面。

## Open Questions（均已决，实现按此执行）

- **清扫开关**：**加** `verify.serving_reclaim.enabled`（缺省 `true`），并在
  `VerifyPanel` 提供 Switch —— 遵循项目约定「新增配置项必须带 Dashboard 界面」
  （同约定见 `spec/archive/2026-09-15-add-impl-wip-checkpoint/proposal.md:13`）。
  受管键落点见 tasks 4.2 列出的五处；漏掉 `_SYNC_PAGE_KEYS["verify"]`
  （`config_admin.py:1417`）会让界面开关的写入被静默丢弃。
- **宽限期取值**：**不新增键、不复用** `admin.escalation_cooldown_minutes`
  （语义为管理员升级静默期），改用模块常量 `RECLAIM_GRACE_SECONDS = 600`。
