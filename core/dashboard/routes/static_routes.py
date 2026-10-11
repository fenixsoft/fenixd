"""static_routes.py — H10 静态/截图（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的静态资源方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。`_HASHED_STATIC_RE` 类属性随本
mixin 迁移；`_GZIP_EXT`/`_GZIP_MIN`/`_maybe_gzip` 在 H0 底座
（routes/base.py），经继承解析。
"""

from __future__ import annotations

import gzip
import mimetypes
import os
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
    # 同名重写，且键取自读 body 之前那次 stat——保证键与载荷出自同一文件
    # 版本（code-review item b0021abda19f）；单文件超上限不入缓（大小守卫），
    # 条目数超限整体清空（简单有界，防长生命周期下缓存无界增长）。
    _GZIP_PAYLOAD_CACHE_MAX_BYTES = 2 * 1024 * 1024
    _GZIP_PAYLOAD_CACHE_MAX_ENTRIES = 16
    # 并发（code-review item cfacda63459c）：类级共享、无锁，安全性依赖
    # CPython dict 单操作原子性（GIL）；value 为不可变 bytes、key 含文件
    # 版本，并发最坏只是回填互相覆盖或 clear 后重复压缩——接受该竞态，
    # 无结构性损坏。
    _gzip_payload_cache: Dict[tuple, bytes] = {}

    def _serve_static(self, filename: str):
        # NUL 字节混入 Path 拼接后 .resolve() 抛 ValueError（embedded null
        # byte，code-review item 747894f47c57），否则会穿透为不透明 500；
        # 按本方法对非法路径的既有语义答 404。
        if "\x00" in filename:
            self._error(404, "Not Found")
            return
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
        # spec 段防穿越（code-review item 5544a9f69b3b，critical）：spec 解码后
        # 可能还原出「..」组件——它会在 .resolve() 之前被嵌入基础目录，把
        # screenshots_dir 本身搬迁到约束目录之外（如
        # /screenshots/<project>/..%2F..%2Ftmp%2Fscreenshots），此时下方
        # target.is_relative_to(screenshots_dir) 对搬迁后目录内任意文件平凡
        # 通过。先校验 spec 不含「..」路径组件再拼接；file_part 的「..」仍由
        # 既有 resolve + is_relative_to 兜底（基础目录此后不可被搬迁）。
        #
        # 绝对路径形态（code-review item 4d4c8e4f2f4b，critical）：path 取自
        # urlparse 不解码 %2F，split 后上方 unquote 可还原出绝对段（如
        # /screenshots/<project>/%2Ftmp%2Ffoo/x.png → spec == '/tmp/foo'）；
        # pathlib 拼接遇绝对段会整体丢弃前缀，同样把 screenshots_dir 搬迁到
        # 约束目录之外，令包含检查平凡通过。与「..」搬迁同属攻击面，一并拒绝。
        spec_norm = spec.replace("\\", "/")
        if (
            not spec_norm
            or spec_norm in (".", "..")
            or ".." in spec_norm.split("/")
            or spec_norm.startswith("/")
            # NUL 字节（%00 解码产物）会让下方 .resolve() 抛 ValueError
            # （code-review item 747894f47c57）穿透为 500，一并拒绝
            or "\x00" in spec
        ):
            self._error(403, "Forbidden")
            return
        # 剩余部分一并 decode（code-review item 206cc192537f）：SPA 以
        # encodeURIComponent(file) 构建 URL，文件名含空格/#/%/非 ASCII 的截图
        # 在网络上恒为 percent-encoded，不解码则合法图片 404。解码后可能还原
        # 出「..」，由下方 resolve + is_relative_to 包含检查兜底。
        file_part = urllib.parse.unquote("/".join(parts[4:]))
        # 同上（code-review item 747894f47c57）：file_part 经 unquote 可能
        # 还原出 NUL 字节，混入下方 Path 拼接后 .resolve() 抛 ValueError
        # 穿透为不透明 500，按本文件对非法路径的既有语义答 403。
        if "\x00" in file_part:
            self._error(403, "Forbidden")
            return

        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            # 未知/非活跃项目答 404（code-review item bd493b870156）：与本包
            # 其余路由（spec_routes/run_routes/project_routes/code_review_routes
            # 均为 404 project not found）语义一致；403 会区分「项目存在性」
            # 并把鉴权失败与资源缺失混同。
            self._error(404, "project not found")
            return

        # 拼接刻意用原始 spec 而非上方校验用的 spec_norm（code-review item
        # 4ff940f60087）：前提是仅 POSIX——反斜杠不作分隔符折叠，含「\」的
        # spec 在磁盘上是单个目录名，校验（对 spec_norm）严格保守于拼接
        # （对原始 spec），穿越防护不受影响；若移植到反斜杠作分隔符的平台
        # （Windows），两处须同步改用 spec_norm。
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

    def _hashed_gzip_payload(self, path: Path, body: bytes,
                             st: Optional[os.stat_result] = None) -> Optional[bytes]:
        """hashed 不可变 bundle 的 gzip 载荷（缓存命中/回填）；不压缩返回 None。

        调用方须自行保证客户端 Accept-Encoding 含 gzip（下方 _send_file 已
        守卫）。非 hashed 文件仍逐请求压缩（内容可变，不可缓存）。st 须为
        调用方读取 body 之前取得的 stat 结果（code-review item b0021abda19f），
        保证缓存键与 body 出自同一文件版本；未传入时兜底自取。
        """
        if path.suffix.lower() not in self._GZIP_EXT:
            return None
        immutable = (
            path.name != "index.html"
            and self._HASHED_STATIC_RE.search(path.name) is not None
        )
        if st is None:
            try:
                st = path.stat()
            except OSError:
                st = None
        key = None
        if immutable and st is not None:
            key = (str(path), st.st_size, st.st_mtime_ns)
        if key is not None:
            cached = self._gzip_payload_cache.get(key)
            if cached is not None:
                return cached
        if len(body) < self._GZIP_MIN:
            return None
        payload = gzip.compress(body, 5)
        # 条目数清空以「本次确要插入」为前提（code-review item 1dfa37965c96）：
        # 超过单文件上限不入缓时不得触碰既有缓存，否则持续访问超大 hashed
        # bundle 会反复清空其他条目，令小文件缓存形同虚设。
        if key is not None and len(body) <= self._GZIP_PAYLOAD_CACHE_MAX_BYTES:
            if len(self._gzip_payload_cache) >= self._GZIP_PAYLOAD_CACHE_MAX_ENTRIES:
                self._gzip_payload_cache.clear()
            self._gzip_payload_cache[key] = payload
        return payload

    def _send_file(self, path: Path, ctype: str, cache: str = "no-cache",
                   extra_headers: "list[tuple[str, str]] | None" = None):
        # 先 stat 后读（code-review item b0021abda19f）：gzip 缓存键的
        # (size, mtime_ns) 必须与 body 出自同一文件版本。若读后再 stat，
        # 两步之间文件被原地重写时键描述新版本、载荷却是旧内容的 gzip，
        # 此后同名请求恒命中陈旧 bundle；读前 stat 则键描述旧版本，重写
        # 后自然 miss 重压，不会以新键长期污染缓存。
        try:
            st = path.stat()
        except OSError:
            st = None
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self._mark_response_started()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        for _name, _value in (extra_headers or ()):
            self.send_header(_name, _value)
        # Vary 无条件发送（与 base._maybe_gzip 口径对齐，同源结论
        # f812b5255a66 / 本条 858b231045be）：响应是否压缩随 Accept-Encoding
        # 变化，非压缩副本缺 Vary 时中介缓存可能把 identity 副本复用给支持
        # gzip 的下游客户端——Cache-Control immutable 的 hashed bundle 上
        # 即构成长期缓存正确性缺口。
        self.send_header("Vary", "Accept-Encoding")
        if path.suffix.lower() in self._GZIP_EXT and self._wants_gzip():
            payload = self._hashed_gzip_payload(path, body, st)
            if payload is not None:
                self.send_header("Content-Encoding", "gzip")
                body = payload
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)