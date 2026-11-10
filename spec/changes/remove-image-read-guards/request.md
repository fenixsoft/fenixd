立项移除这两个守卫

背景：现模型已支持图像输入，上一轮已移除项目级提示词中的「当前模型无法读图」描述；但两条车道的读图拦截守卫仍在实际阻断读图——fenix 主车道 `.fenix/hooks/block-image-read.py`（经 `.fenix/agent-settings.json` 注册 PreToolUse Read 拦截）与 dsh 通道 `dsh-bundle` 等价守卫（三守卫等价契约成员）。本 SPEC 将两守卫整体退役；主树写拦截与场景批处理两守卫保留不动。
