"""
registry.py — 多项目发现与注册（dashboard-server D3）。

中心配置文件 `~/.config/fenixd/dashboard.yaml`：
    port: 8787
    projects:
      - name: <别名>
        path: <项目绝对路径>
    scan_dirs:
      - <父目录>

`discover()` 合并显式 projects 与 scan_dirs 扫描结果；扫描仅当目录存在
`.fenix/STATE.md` 即识别为 Fenixd 项目（无需 `.fenix/config.yaml`）。显式注册的
项目始终出现在监控列表（即使目录不存在，标记 exists=False）。

默认扫描：`scan_dirs` 未配置（或为空）时，自动以用户主目录 `~` 为唯一扫描根
遍历一级子目录做发现（自动发现为主）；显式配置 `scan_dirs` 可覆盖该默认。
显式注册（`add_project`）为扫描的补充，可纳入扫描范围之外的路径。
"""

import errno
import logging
import errno
import logging
import os
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8787
DEFAULT_CONFIG = Path.home() / ".config" / "fenixd" / "dashboard.yaml"


class Registry:
    """读写监控配置并执行多项目发现。"""

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG

    # ── 忽略列表（软删除：被忽略路径不再被显式/扫描发现） ──────────

    @staticmethod
    def _norm(path) -> str:
        """规范化路径（展开 ~ 与软链接，解析为绝对路径）。"""
        try:
            return str(Path(path).expanduser().resolve())
        except (OSError, RuntimeError):
            return str(Path(path).expanduser())

    # ── 子目录探测（容错三态：present / absent / unreadable）──────────

    _PROBE_PRESENT = "present"
    _PROBE_ABSENT = "absent"
    _PROBE_UNREADABLE = "unreadable"

    # pathlib.Path.is_file()/_is_dir() 内部只吞 ENOENT/ENOTDIR/EBADF/ELOOP，
    # 但 EIO 等其它 OSError 会直接上抛。这里显式捕获以区分「正常不存在」与「不可读」。
    _ABSENT_ERRNOS = {errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP}

    def probe_child(self, child: Path) -> str:
        """对扫描候选子目录执行 is_dir() + .fenix/STATE.md is_file() 探测。

        返回三态：
          present    —— 是目录且存在 .fenix/STATE.md（Fenixd 项目）
          absent     —— 正常不存在（非目录，或缺少 STATE.md），静默
          unreadable —— 探测抛 OSError（含 EIO），写 WARNING 日志后跳过

        实现须显式 try/except OSError——MUST NOT 依赖 pathlib 默认吞异常
        （其 _IGNORED_ERROS 不含 EIO，EIO 会直接上抛）。
        """
        # 目录类型判断
        try:
            if not child.is_dir():
                return self._PROBE_ABSENT
        except OSError as exc:
            return self._log_unreadable(child, exc)

        # .fenix/STATE.md 存在性探测
        state_path = child / ".fenix" / "STATE.md"
        try:
            if not state_path.is_file():
                return self._PROBE_ABSENT
        except OSError as exc:
            return self._log_unreadable(child, exc)

        return self._PROBE_PRESENT

    @staticmethod
    def _log_unreadable(path: Path, exc: OSError) -> str:
        """对「不可读」子目录写一条 WARNING 日志并返回 unreadable 三态。"""
        errno_code = errno.errorcode.get(exc.errno, "?")
        logger.warning(
            "发现层跳过不可读路径 %s（%s, errno=%s）: %s",
            path,
            errno_code,
            exc.errno,
            exc,
        )
        return Registry._PROBE_UNREADABLE

    # ── 配置读写 ─────────────────────────────────────────────

    def load(self) -> dict:
        """读取配置；缺失/损坏时返回默认结构。"""
        defaults = {"port": DEFAULT_PORT, "projects": [], "scan_dirs": [], "ignored": []}
        if not self.config_path.exists():
            return defaults
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError):
            return defaults
        if not isinstance(data, dict):
            return defaults
        out = {
            "port": data.get("port") or DEFAULT_PORT,
            "projects": data.get("projects") or [],
            "scan_dirs": data.get("scan_dirs") or [],
            "ignored": data.get("ignored") or [],
        }
        if not isinstance(out["projects"], list):
            out["projects"] = []
        if not isinstance(out["scan_dirs"], list):
            out["scan_dirs"] = []
        if not isinstance(out["ignored"], list):
            out["ignored"] = []
        return out

    def save(self, data: dict):
        """写回配置（确保目录存在）。"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(self.config_path)

    # ── 发现 ─────────────────────────────────────────────────

    def discover(self) -> list:
        """合并显式配置与目录扫描，返回 [{name, path, discovered, exists}]。

        合并后按 `ignored` 列表过滤规范化路径——被忽略项目（无论显式注册
        还是自动发现）一律不再出现在监控列表，实现软删除语义。
        """
        data = self.load()
        ignored = {self._norm(x) for x in data.get("ignored", []) if x}
        projects = []
        seen = set()

        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            raw = p.get("path", "")
            try:
                rp = Path(raw).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            key = str(rp)
            if key in ignored:
                continue
            if key in seen:
                continue
            seen.add(key)
            name = p.get("name") or (rp.name or key)
            projects.append(
                {
                    "name": name,
                    "path": key,
                    "discovered": False,
                    "exists": rp.is_dir(),
                }
            )

        # 扫描根：显式配置 scan_dirs 时沿用该配置（覆盖默认）；未配置（或为空）
        # 时默认以用户主目录 ~ 为唯一扫描根，遍历其一级子目录做自动发现。
        scan_dirs = data.get("scan_dirs", [])
        if not scan_dirs:
            scan_dirs = [str(Path.home())]
        for sd in scan_dirs:
            base = Path(sd).expanduser()
            try:
                if not base.is_dir():
                    continue
            except OSError:
                continue
            try:
                children = sorted(base.iterdir())
            except OSError:
                # 扫描根整体不可读：跳过该根，继续处理其余扫描根与显式项目
                continue
            for child in children:
                # 忽略过滤前置：任何可能抛 OSError 的探测之前先短路，
                # 使软删除对不可读路径同样生效（写侧与读侧共用 _norm）。
                key = self._norm(child)
                if key in ignored:
                    continue
                if key in seen:
                    continue
                # 三态探测：present（Fenixd 项目）/ absent（静默跳过）/
                # unreadable（写 WARNING 日志后跳过），均不中断整体发现。
                if self.probe_child(child) != self._PROBE_PRESENT:
                    continue
                seen.add(key)
                projects.append(
                    {
                        "name": child.name or key,
                        "path": key,
                        "discovered": True,
                        "exists": True,
                    }
                )

        return projects

    # ── 注册 ─────────────────────────────────────────────────

    def add_project(self, path, name=None) -> tuple:
        """注册项目到配置（按路径去重）。

        Returns: (added: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            return False, f"无效路径: {path}"
        key = str(rp)

        data = self.load()
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            try:
                existing = str(Path(p.get("path", "")).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
            if existing == key:
                return False, f"项目已在监控列表: {key}"

        if not (rp / ".fenix" / "STATE.md").is_file():
            return False, f"目录不是 Fenixd 项目（缺少 STATE.md）: {key}"

        data.setdefault("projects", []).append(
            {
                "name": name or (rp.name or key),
                "path": key,
            }
        )
        self.save(data)
        return True, f"已注册项目: {key}"

    def remove_project(self, path) -> tuple:
        """从配置 `projects` 移除显式注册的项目（按规范化路径匹配）并写回。

        未在配置中显式注册（含仅由扫描自动发现的项目）时返回未变更提示，
        不报错。返回: (removed: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            return False, f"无效路径: {path}"
        key = str(rp)

        data = self.load()
        remaining = []
        removed = False
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                remaining.append(p)
                continue
            try:
                existing = str(Path(p.get("path", "")).expanduser().resolve())
            except (OSError, RuntimeError):
                remaining.append(p)
                continue
            if existing == key:
                removed = True
                continue
            remaining.append(p)

        if not removed:
            return False, f"项目未在监控列表（无法移除）: {key}"
        data["projects"] = remaining
        self.save(data)
        return True, f"已从监控列表移除: {key}"

    def add_ignored(self, path) -> tuple:
        """把规范化路径追加进 `ignored` 列表（去重）并写回。

        软删除项目的实现：被忽略路径不再被显式/扫描发现（discover 过滤）。
        项目文件、配置、数据全部保留；恢复 = 手工从列表移除该路径。

        Returns: (added: bool, message: str)
        """
        try:
            key = self._norm(path)
        except (OSError, RuntimeError):
            return False, f"无效路径: {path}"

        data = self.load()
        ignored = data.get("ignored") or []
        if not isinstance(ignored, list):
            ignored = []
        if key in {self._norm(x) for x in ignored if x}:
            return False, f"项目已在忽略列表: {key}"
        ignored.append(key)
        data["ignored"] = ignored
        self.save(data)
        return True, f"已加入忽略列表: {key}"

    def is_ignored(self, path) -> bool:
        """查询某路径是否已被忽略（按规范化路径比较）。"""
        try:
            key = self._norm(path)
        except (OSError, RuntimeError):
            return False
        data = self.load()
        return key in {self._norm(x) for x in data.get("ignored", []) if x}

    def list_projects(self) -> list:
        """仅返回配置中显式注册的项目（供 --list-projects）。"""
        data = self.load()
        out = []
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            out.append(
                {
                    "name": p.get("name"),
                    "path": p.get("path"),
                }
            )
        return out
