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
`STATE.md` 即识别为 Fenixd 项目（无需 `.fenix/config.yaml`）。显式注册的
项目始终出现在监控列表（即使目录不存在，标记 exists=False）。

默认扫描：`scan_dirs` 未配置（或为空）时，自动以用户主目录 `~` 为唯一扫描根
遍历一级子目录做发现（自动发现为主）；显式配置 `scan_dirs` 可覆盖该默认。
显式注册（`add_project`）为扫描的补充，可纳入扫描范围之外的路径。
"""

import os
import yaml
from pathlib import Path

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
            projects.append({
                "name": name,
                "path": key,
                "discovered": False,
                "exists": rp.is_dir(),
            })

        # 扫描根：显式配置 scan_dirs 时沿用该配置（覆盖默认）；未配置（或为空）
        # 时默认以用户主目录 ~ 为唯一扫描根，遍历其一级子目录做自动发现。
        scan_dirs = data.get("scan_dirs", [])
        if not scan_dirs:
            scan_dirs = [str(Path.home())]
        for sd in scan_dirs:
            base = Path(sd).expanduser()
            if not base.is_dir():
                continue
            try:
                children = sorted(base.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if not (child / "STATE.md").is_file():
                    continue
                rp = child.resolve()
                key = str(rp)
                if key in ignored:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                projects.append({
                    "name": rp.name or key,
                    "path": key,
                    "discovered": True,
                    "exists": True,
                })

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

        if not (rp / "STATE.md").is_file():
            return False, f"目录不是 Fenixd 项目（缺少 STATE.md）: {key}"

        data.setdefault("projects", []).append({
            "name": name or (rp.name or key),
            "path": key,
        })
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
            out.append({
                "name": p.get("name"),
                "path": p.get("path"),
            })
        return out
