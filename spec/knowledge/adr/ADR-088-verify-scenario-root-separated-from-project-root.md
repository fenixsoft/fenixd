# ADR-088：验证执行根与簿记根分离（scenario_root）

date: 2026-09-14
status: accepted

## Context

cli 型验证场景缺省 cwd 解析到主树根，与「cwd 相对验证树根」契约相悖：serving worktree 轮次下场景的 seed 型相对路径写入落主树（写主树 STATE/spec 目录，夹具 spec 复活被 daemon 收编烧钱）；断言读写同错一致时场景 pass 不可发现。实例路径登记在服务缓存中，却从未传给验证引擎。

## Decision

- 引擎增可选 `scenario_root` 参数：缺省 None 回退 project_root（无 worktree 轮与存量调用零变化）；serving worktree 建立后取其根传入，新建与实例复用两条路径都必须带出，Runner 分发透传，仅 cli runner 的 cwd 解析消费。
- 簿记与执行根分离是硬边界：`.fenix/verify-progress` 等引擎簿记路径恒用 project_root，不换 scenario_root——验收逐点核对，防接线时顺手替换。
- 仓库内文件 worktree 轮下读 worktree（同 HEAD 检出内容一致）；gitignored / 仓库外路径本就不该被场景依赖——`.fenix` 写入正是要隔离的对象。确需主树运行时状态的场景必须显式声明绝对路径或 cwd。
- 不做「主树写拦截」类守卫：治本靠 cwd 正确，守卫留待后续按需立项。

## Consequences

- seed 型写入物理隔离在验证树内，验证夹具不再污染主树、不再复活被收编。
- 簿记路径零变化；web/api runner 按 base_url 访问实例，无文件系统写路径依赖，不受影响。
- 纯静态无实例轮的 seed 场景仍写主树——现状该类契约不含 seed 型场景；未来出现由守卫 SPEC 接管。
