<!-- knowledge: capability=push-credential-environment rev=1 sources=spec/changes/fix-push-credential-env-and-retry-rearm -->

# 推送凭证环境确定性

done→pushed 自动推送的 git 子进程环境与凭证确定性：HOME 单源解析与显式注入、凭证双腿通道、承载层 HOME 基线与启动凭证自检。退避续推消费通道见 [done 态推送退避续推](push-retry-recovery.md)，推送引用与退避收敛语义见 [推送引用生命周期卫生](push-ref-hygiene.md)。

## 现行规则

- 环境显式注入：推送的 git 子进程以单源解析器产出的显式 `env=` 运行，不裸继承 daemon 进程环境。HOME 三级解析序——daemon env 的非空 `HOME` → `pwd` passwd 目录 → 配置 `pm.push.credential_home`（可选覆盖）；三级皆空时不注入 HOME（凭证回落 URL 单腿）且不抛异常，由启动自检就此状态告警。
- 凭证双腿并存：凭证通道 = remote URL 内嵌 token + credential helper 文件，任一可用即可推送，两通道并存兼容（git 先查 helper 再用 URL 凭证）。helper 参数以**单一 argv 元素**追加（`["-c", "credential.helper=store --file=<abs>"]`）——helper 值内的 `--file=` 属 credential.helper 配置串、由 git 按空白切分为子参数，拆成多个 argv 元素会让 `--file=` 被解析为顶层未知选项致推送必败。文件路径默认＝解析后 HOME 下的 `.git-credentials`，可经 `pm.push.credential_file` 覆盖；解析路径不存在时不追加该参数（不静默创建空凭证文件制造「有凭证」假象）；配置显式置空字符串即关断兜底。
- 承载层 HOME 基线：`capture_env_candidate` 捕获 env 候选稿时检查非空 `HOME`，缺失则以解析器单源补齐并按 PATH 同款格式注释留痕；已含 HOME 时产物逐字节不变。`render_project_unit` 渲染的 unit 含 `Environment=HOME=<resolved>` 保底行——EnvironmentFile 缺席或缺 HOME 键时 daemon 仍带 HOME 启动；env 文件在场且含 HOME 时其值照常覆盖保底行。迁移摘要输出 HOME 卫生结论（完整 / 补齐 / 缺失且无法解析）。
- 启动凭证自检：daemon 启动自检链含推送凭证探测（纯本地读取，不做网络探测）：解析 HOME 是否为存在目录、凭证文件是否在场、任一 remote URL 是否含内嵌凭证；双腿皆缺或 HOME 解析失败发 WARNING 自检告警（含归因与人工处置指引），fail-open——不阻断启动、不改变派发行为。单腿可用属可运行状态，不告警。

## 代码锚点

- 单源解析器：`core/git_env.py`（`resolve_git_env` / `credential_helper_args` / `GitEnv`）
- 消费方：`core/pm_engine/engine.py` `_git_push_ref`（显式 env 注入 + helper 追加）；`fenixd.py` `_startup_credential_precheck`、`_url_has_embedded_credential`（启动自检探测）；`core/systemd_hosting.py` `capture_env_candidate` / `render_env_file` / `render_project_unit`（HOME 基线补齐留痕与 unit 保底行）；`bin/migrate_to_systemd.py`（迁移摘要 HOME 卫生结论）

## 溯源

- 2026-11-09 fix-push-credential-env-and-retry-rearm（spec/changes/fix-push-credential-env-and-retry-rearm/） — 新增本能力：HOME 三级解析单源与显式 env 注入、credential helper 文件兜底双腿、承载层捕获与 unit 模板 HOME 基线、启动凭证自检告警。动因实测：cloud-phone 事故 systemd 承载 daemon 无 HOME，git 报 could not read Username / $HOME not set，凭证只剩 URL 内嵌 token 单腿、token 失效后全项目推送瘫痪
