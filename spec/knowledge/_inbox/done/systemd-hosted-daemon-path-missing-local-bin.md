# systemd 承载 daemon 裸环境三连缺陷：PATH 缺 ~/.local/bin、无 HOME、无 IS_SANDBOX（fenix-desktop 11-05 取证）

## 现象

fenix-desktop 项目 SPEC `token-usage-monitor-panel` 起草评审失败冻结：三次评审 run
在 3 秒内连续 spawn 秒败（`[Errno 2] No such file or directory: 'claude'`，零 API 轮次），
触发 `spec-review-incomplete` 升级信号，spec 被 machine 冻结（原状态 reviewing）。
环境修复后又暴露第二层失败：`--dangerously-skip-permissions cannot be used with
root/sudo privileges`（claude CLI 在 root 下拒绝 bypassPermissions）。

## 取证（三层缺陷，全在 systemd 承载链的环境面）

1. **PATH 缺 `~/.local/bin`**：unit 写 `EnvironmentFile=-/root/fenix-desktop/.fenix/systemd.env`
   （`-` 前缀=文件可缺省，缺失静默跳过）；该文件一直未提升落盘 → daemon PATH =
   systemd 默认七目录 → `claude`（在 `/root/.local/bin/claude`）spawn FileNotFoundError。
2. **无 HOME/USER/LOGNAME**：systemd 对无 `User=` 的 root 服务不下发 HOME →
   claude CLI（node）找不到 `~/.claude`。
3. **无 IS_SANDBOX**：claude CLI 在 root/sudo 下拒绝 bypassPermissions 模式
   （错误文案以旧旗标名 `--dangerously-skip-permissions` 表述），除非 env 带
   `IS_SANDBOX=1`。框架 runner 恒传 `permission_mode="bypassPermissions"`
   （runner.py SpawnRequest 单点），`IS_SANDBOX` 仅出现在 systemd_hosting.py
   的会话身份 denylist（候选稿捕获过滤）——即捕获机制还主动滤掉该键，且无任何
   机制补给。fenixd 主项目 daemon 从交互会话启动**继承** `IS_SANDBOX=1`/HOME/
   完整 PATH，故同日一切正常——「能跑」依赖的是启动方式巧合，非设计保证。

对照修复（fenix-desktop/.fenix/systemd.env 提升稿）：PATH（含 ~/.local/bin）+
HOME/USER/LOGNAME + IS_SANDBOX=1，`systemctl restart` 后评审重派即成功
（spec-review run 出现真实 API 往返，spec 通过评审进入 implementing）。

## 规则

- systemd 承载的 daemon 必须保证 `EnvironmentFile` 指向的 env 文件真实落盘，
  最小集：`PATH`（含 agent CLI 所在目录）、`HOME`/`USER`/`LOGNAME`、
  `IS_SANDBOX=1`（root 下 claude bypassPermissions 的放行键）。`-` 前缀的可缺省
  语义让缺文件变成静默运行时环境劣化——unit 安装成功 ≠ 环境就绪。
- denylist（SESSION_IDENTITY_DENYLIST_PREFIXES）过滤的语义边界：CLAUDE_PID/
  CLAUDECODE/CLAUDE_CODE_* 等会话身份键必须滤（自杀扳机/自证行为变异）；
  IS_SANDBOX 被同一前缀族滤掉属误伤面——候选稿提升时需人工补回，或承载层
  安装/提升时显式追加（框架侧缺口，待立项）。
- 诊断口径：spawn 层失败三查——`/proc/<daemon_pid>/environ` 对表 `which claude`；
  run jsonl 零 API 事件即 spawn 层死亡（勿信归因文本里的「模型链/配置问题」）；
  错误文案见 `--dangerously-skip-permissions` + root 字样即 IS_SANDBOX 缺席。

## 关联

- 升级链行为面（本案触发链：评审失败 → spec-review-incomplete → 链 frozen
  预检 deferred → 链内零痕迹等人工）见 spec/knowledge/domains/admin-ops/
  escalation-chain.md；同日用户定调已把该缺口改道为「frozen 件直达 Arbiter
  冻结鉴定」，见该页 Arbiter 必经不变式。
- 失败的 run jsonl 只有 provider_marker+prompt 头（18 KB 元数据），无任何
  API 事件——spawn 层死亡特征，勿信后续归因文本里的「模型链/配置问题」措辞。
