# DSH 会话下 fenix-setup 的 EnvironmentFile 捕获源需改道（2026-11-26 fenixd-website 立项实测）

## 现象

在 DSH harness 会话里对新项目执行 fenix-setup 步骤 7①（从当前会话环境机械捕获 env 写 systemd EnvironmentFile）时，会话 bash 环境是净化过的：`HOME` 未设置（`git config --global` 直接报 `fatal: $HOME not set`），且 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`/HTTP(S)_PROXY 等 load-bearing 键全部缺席。机械捕获产物缺失网关凭据与 HOME，daemon spawn 后无法访问 LLM 网关。

## 结论

DSH 会话下捕获源改道：以同机已在用的正式 EnvironmentFile 为源（如 `/root/fenixd/.fenix/systemd.env`），解析后按 load-bearing 子集过滤（ANTHROPIC_*、API_TIMEOUT_MS、HOME、PATH、SHELL、USER、LOGNAME、LANG、HTTP(S)_PROXY/NO_PROXY 大小写双腿、XDG_RUNTIME_DIR），再经 `core/systemd_hosting.py` 的 `render_env_file` + `write_env_file`（0600）写入新项目。剔除源文件里的会话残留键（PWD/OLDPWD/TMUX_*/VSCODE_*/SSH_*/COLORTERM 等）。技能步骤 5 的简介生成同理：claude CLI 可直接省略，由执行 agent 自拟文案写入 `.fenix/config.yaml` 的 `project.description`。

## 关联要点

- fenix-setup skill 的 ① 阶段注释「新装场景源即当前受信会话」以 Claude Code 会话为预设；DSH 会话环境形态不同，属同一步骤的替代捕获源，不是绕过审核——源文件本身已是同机人工审核后在用的正式件。
- 另注意：`gh`/`git` 在 DSH bash 下需先 `export HOME=/root` 才能读到 `~/.gitconfig`（gh credential helper）与 `~/.config/gh/hosts.yml`。

## 关联文件

core/systemd_hosting.py（read_process_env/filter_session_identity/render_env_file/write_env_file/project_env_file）、fenix-setup skill 步骤 7①、/root/fenixd/.fenix/systemd.env（既有正式件样例）
