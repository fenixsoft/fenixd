"""help_routes.py — H8 help docs。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import errno
import re
from pathlib import Path


class H8HelpRoutesMixin:
    """H8 help docs。"""

    @staticmethod
    def _help_doc_title(content: str) -> str:
        """从 Markdown 原文解析首个一级标题（# 行）作为文档标题。

        兼容「#标题」「#\t标题」等无空格 ATX 变体（code-review fcff933f40ad）；
        ## 及更深层级不视为一级标题。无一级标题时回退为去后缀文件名，
        保证清单端点始终有可展示标题。
        """
        for line in content.splitlines():
            # code-review fcff933f40ad：#(?!#) 排除 ## 及更深层级，\s* 兼容无空格写法
            m = re.match(r"#(?!#)\s*(.+)", line.strip())
            if m:
                return m.group(1).strip()
        return ""


    def _api_help_docs(self) -> dict:
        """GET /api/help/docs

        列出框架仓库 docs/help/ 下全部合法 .md 文档，返回 [{name, title}]。
        - README.md 置顶（默认文档），其余按文件名字典序（NN- 编号天然有序）
        - 目录缺失 / 为空 → 空列表（前端空态）
        - 非 .md 文件跳过不计入清单
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3
        help_dir = _server_mod.HELP_DOCS_DIR.resolve()
        if not help_dir.is_dir():
            return {"docs": []}
        try:
            files = list(
                p for p in help_dir.iterdir() if p.is_file() and _server_mod.HELP_DOC_NAME_RE.match(p.name)
            )
        except OSError:
            return {"docs": []}
        docs = []
        try:
            for f in files:
                title = ""
                try:
                    title = self._help_doc_title(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    title = ""
                docs.append({"name": f.name, "title": title or f.name[:-3]})
        except OSError:
            return {"docs": []}
        # README 置顶（设计 D5：文件名即路由参数，README 为默认文档）
        docs.sort(key=lambda d: (d["name"] != "README.md", d["name"]))
        return {"docs": docs}


    def _api_help_doc(self, query):
        """GET /api/help/doc?name=<file>

        返回单篇帮助文档 Markdown 原文 {name, content, title}。
        - 名字不匹配白名单（[A-Za-z0-9._-]+\.md）→ 400（防穿越，不泄露信息）
        - 解析后 real path 不在 docs/help/ 内 → 400
        - 目录缺失 / 文件不存在 → 404
        - 存在但读取失败（权限/IO）→ 500，不与「不存在」混淆
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3
        name = query.get("name", [None])[0] or ""
        if not name or not _server_mod.HELP_DOC_NAME_RE.match(name):
            self._error(400, "invalid help doc name")
            return
        help_dir = _server_mod.HELP_DOCS_DIR.resolve()
        target = (help_dir / name).resolve()
        # 防穿越：解析后必须仍位于 docs/help/ 内（dirs 缺省，不会跑到 docs 其它处）
        if not target.is_relative_to(help_dir):
            self._error(400, "invalid help doc name")
            return
        if not target.is_file():
            self._error(404, "help doc not found")
            return
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # code-review 4c1dd43dbfbd：is_file() 已通过后的 OSError 多为
            # 权限/IO 故障，与「不存在」同报 404 会让排查失焦（对齐
            # settings_routes._api_prompts_get 读失败转可读 500 的惯例）；
            # 仅 ENOENT/ENOTDIR（检查与读取之间被删的竞态）仍按 404。
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                self._error(404, "help doc not found")
            else:
                self._error(500, f"help doc read failed: {exc}")
            return
        self._json(
            {
                "name": name,
                "title": self._help_doc_title(content) or name[:-3],
                "content": content,
            }
        )

