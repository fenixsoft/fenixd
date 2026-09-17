"""static_routes.py — H10 静态/截图（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的静态资源方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。`_HASHED_STATIC_RE` 类属性随本
mixin 迁移；`_GZIP_EXT`/`_GZIP_MIN`/`_maybe_gzip` 在 H0 底座
（routes/base.py），经继承解析。
"""

from __future__ import annotations

import mimetypes
import re
import urllib.parse
from pathlib import Path

from core.dashboard.server import ALLOWED_IMAGE_EXT  # noqa: E402 — 常量门面


class H10StaticRoutesMixin:
    """H10 静态/截图（design D1 表 C H10）。"""

    _HASHED_STATIC_RE = re.compile(r"\.[0-9a-f]{8,}(?:\.async)?\.(?:js|css)$")

    def _serve_static(self, filename: str):
        static_root = self.server.static_dir.resolve()
        target = (static_root / filename).resolve()
        # 防路径穿越：解析后必须仍在 static 目录内
        if not target.is_relative_to(static_root):
            self._error(404, "Not Found")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # v3 SPA 直接挂载在 / 时，index.html 内相对资源（./umi.js）
            # 会以根路径请求；回退映射到 dist/ 目录
            target = static_root / "dist" / filename
            if not target.is_relative_to(static_root) or not target.is_file():
                self._error(404, "Not Found")
                return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        # 构建产物文件名带内容 hash，可安全长缓存；index.html 不缓存
        cache = "no-cache"
        if target.name != "index.html" and self._HASHED_STATIC_RE.search(target.name):
            cache = "max-age=31536000, immutable"
        self._send_file(target, ctype, cache=cache)

    def _serve_screenshot(self, path: str):
        # /screenshots/<project>/<spec>/<file>
        parts = path.split("/")
        # ['', 'screenshots', project, spec, file...]
        if len(parts) < 5:
            self._error(404, "Not Found")
            return
        project_name = urllib.parse.unquote(parts[2])
        spec = urllib.parse.unquote(parts[3])
        file_part = "/".join(parts[4:])

        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(403, "Forbidden")
            return

        screenshots_dir = (
            Path(project["path"]) / ".fenix" / "verify-progress" / spec / "screenshots"
        ).resolve()
        target = (screenshots_dir / file_part).resolve()

        # 防路径穿越：解析后必须仍位于该项目 screenshots 目录内
        if not target.is_relative_to(screenshots_dir):
            self._error(403, "Forbidden")
            return
        if not target.is_file() or target.suffix.lower() not in ALLOWED_IMAGE_EXT:
            self._error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "image/png"
        self._send_file(target, ctype)

    def _send_file(self, path: Path, ctype: str, cache: str = "no-cache"):
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        if path.suffix.lower() in self._GZIP_EXT:
            body = self._maybe_gzip(body)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)