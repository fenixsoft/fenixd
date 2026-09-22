"""static_routes.py — H10 静态/截图（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的静态资源方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。`_HASHED_STATIC_RE` 类属性随本
mixin 迁移；`_GZIP_EXT`/`_GZIP_MIN`/`_maybe_gzip` 在 H0 底座
（routes/base.py），经继承解析。
"""

from __future__ import annotations

import gzip
import mimetypes
import re
import urllib.parse
from pathlib import Path
from typing import Dict, Optional

from core.dashboard.server import ALLOWED_IMAGE_EXT  # noqa: E402 — 常量门面


class H10StaticRoutesMixin:
    """H10 静态/截图（design D1 表 C H10）。"""

    _HASHED_STATIC_RE = re.compile(r"\.[0-9a-f]{8,}(?:\.async)?\.(?:js|css)$")

    # hashed 不可变 bundle 的 gzip 载荷缓存（code-review item 34967a77247a）：
    # ThreadingHTTPServer 的 worker 在 GIL 下串行执行，每请求对同一不可变
    # .js/.css 重压同一字节纯属浪费。仅缓存文件名带内容 hash 的文件
    # （_HASHED_STATIC_RE，index.html 除外）；key 含 (size, mtime_ns) 兜底
    # 同名重写；单文件超上限不入缓（大小守卫），条目数超限整体清空（简单
    # 有界，防长生命周期下缓存无界增长）。
    _GZIP_PAYLOAD_CACHE_MAX_BYTES = 2 * 1024 * 1024
    _GZIP_PAYLOAD_CACHE_MAX_ENTRIES = 16
    _gzip_payload_cache: Dict[tuple, bytes] = {}

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
        # 剩余部分一并 decode（code-review item 206cc192537f）：SPA 以
        # encodeURIComponent(file) 构建 URL，文件名含空格/#/%/非 ASCII 的截图
        # 在网络上恒为 percent-encoded，不解码则合法图片 404。解码后可能还原
        # 出「..」，由下方 resolve + is_relative_to 包含检查兜底。
        file_part = urllib.parse.unquote("/".join(parts[4:]))

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

    def _hashed_gzip_payload(self, path: Path, body: bytes) -> Optional[bytes]:
        """hashed 不可变 bundle 的 gzip 载荷（缓存命中/回填）；不压缩返回 None。

        调用方须自行保证客户端 Accept-Encoding 含 gzip（下方 _send_file 已
        守卫）。非 hashed 文件仍逐请求压缩（内容可变，不可缓存）。
        """
        if path.suffix.lower() not in self._GZIP_EXT:
            return None
        immutable = (
            path.name != "index.html"
            and self._HASHED_STATIC_RE.search(path.name) is not None
        )
        try:
            st = path.stat()
            key = (str(path), st.st_size, st.st_mtime_ns) if immutable else None
        except OSError:
            key = None
        if key is not None:
            cached = self._gzip_payload_cache.get(key)
            if cached is not None:
                return cached
        if len(body) < self._GZIP_MIN:
            return None
        payload = gzip.compress(body, 5)
        if key is not None:
            if len(self._gzip_payload_cache) >= self._GZIP_PAYLOAD_CACHE_MAX_ENTRIES:
                self._gzip_payload_cache.clear()
            if len(body) <= self._GZIP_PAYLOAD_CACHE_MAX_BYTES:
                self._gzip_payload_cache[key] = payload
        return payload

    def _send_file(self, path: Path, ctype: str, cache: str = "no-cache"):
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        if path.suffix.lower() in self._GZIP_EXT and self._wants_gzip():
            payload = self._hashed_gzip_payload(path, body)
            if payload is not None:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
                body = payload
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)