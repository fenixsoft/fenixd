"""
spec_gen.py — fenix 原生 SPEC 生成器。

提供 spec-driven 工作流能力（行为对标原 vendored 的上游 npm 工具链实现）：
- new_change()：创建 change 脚手架（kebab-case 校验、同名拒绝、写 .spec.yaml）
- status()：按依赖顺序计算 artifact 完成状态（done/ready/blocked + missingDeps）
- instructions()：返回指定 artifact 的生成指引（outputPath/instruction/template/dependencies）

schema 数据 vendored 于框架根 schemas/spec-driven/（见其 README），
本模块不依赖 daemon，可独立调用。
"""

import glob
import logging
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "spec-driven"

DEFAULT_SCHEMA = "spec-driven"

_LOGGER = logging.getLogger("fenixd.spec_gen")

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


# ── Schema 加载 ────────────────────────────────────────────────────


def load_schema() -> Dict[str, Any]:
    """读取 vendored `schema.yaml` 并返回解析后的 dict。

    Raises:
        ValueError: schema 缺 'artifacts'，或某 artifact 条目缺必需键
            （id/generates/template）。在加载期集中校验，让 schema 漂移
            可直读定位，而非散落在 status/instructions 里以裸 KeyError 失败。
    """
    schema_path = SCHEMA_DIR / "schema.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    if not isinstance(schema, dict) or "artifacts" not in schema:
        raise ValueError(f"Invalid schema (missing 'artifacts'): {schema_path}")
    if not isinstance(schema["artifacts"], list):
        raise ValueError(
            f"Invalid schema ('artifacts' is not a list): {schema_path}"
        )
    for index, artifact in enumerate(schema["artifacts"]):
        if not isinstance(artifact, dict):
            raise ValueError(
                f"Invalid schema: artifacts[{index}] is not a mapping: {schema_path}"
            )
        missing = [key for key in ("id", "generates", "template") if key not in artifact]
        if missing:
            # id 缺失时用索引占位，保证错误信息仍可定位到具体条目。
            label = artifact.get("id", f"#{index}")
            raise ValueError(
                f"Invalid schema: artifact '{label}' missing required keys "
                f"{missing}: {schema_path}"
            )
    return schema


def _load_template(template_path: str) -> str:
    """读取 schema 的模板文件内容。"""
    template_file = SCHEMA_DIR / "templates" / template_path
    if not template_file.exists():
        raise FileNotFoundError(f"Template not found: {template_file}")
    return template_file.read_text(encoding="utf-8")


# ── 名称校验 ───────────────────────────────────────────────────────


def _validate_name(name: str) -> Optional[str]:
    """kebab-case 名称校验；合法返回 None，否则返回具体错误信息。"""
    if not name:
        return "Change name cannot be empty"
    if not _KEBAB_RE.fullmatch(name):
        if re.search(r"[A-Z]", name):
            return "Change name must be lowercase (use kebab-case)"
        if re.search(r"\s", name):
            return "Change name cannot contain spaces (use hyphens instead)"
        if "_" in name:
            return "Change name cannot contain underscores (use hyphens instead)"
        if name.startswith("-"):
            return "Change name cannot start with a hyphen"
        if name.endswith("-"):
            return "Change name cannot end with a hyphen"
        if "--" in name:
            return "Change name cannot contain consecutive hyphens"
        if re.search(r"[^a-z0-9-]", name):
            return "Change name can only contain lowercase letters, numbers, and hyphens"
        if name[0].isdigit():
            return "Change name must start with a letter"
        return "Change name must follow kebab-case convention (e.g., add-auth, refactor-db)"
    return None


# ── change 脚手架 ──────────────────────────────────────────────────


def new_change(project_root: Path, name: str) -> Path:
    """创建 change 脚手架：建立目录并写入 `.spec.yaml`。

    Raises:
        ValueError: 名称非 kebab-case，或同名 change 已存在（不覆盖）。
    """
    error = _validate_name(name)
    if error:
        raise ValueError(error)

    change_dir = project_root / "spec" / "changes" / name
    if change_dir.exists():
        raise ValueError(f"Change '{name}' already exists at {change_dir}")

    try:
        # 原子建目录判重：并发同名调用只有一个能创建成功，避免先检查后创建的竞态覆写。
        change_dir.mkdir(parents=True)
    except FileExistsError:
        raise ValueError(f"Change '{name}' already exists at {change_dir}") from None
    metadata = f"schema: {DEFAULT_SCHEMA}\ncreated: {date.today().isoformat()}\n"
    try:
        (change_dir / ".spec.yaml").write_text(metadata, encoding="utf-8")
    except Exception:
        # 回滚半成品脚手架：写失败残留的空目录会以 already exists 永久阻塞同名重试。
        shutil.rmtree(change_dir, ignore_errors=True)
        raise
    return change_dir


# ── artifact 状态计算 ──────────────────────────────────────────────


def _is_glob_pattern(pattern: str) -> bool:
    return any(ch in pattern for ch in ("*", "?", "["))


def _artifact_output_exists(change_dir: Path, generates: str) -> bool:
    """判断 artifact 的 `generates` 是否有产出文件。

    简单路径按文件存在判定；glob 模式（如 `specs/**/*.md`）以存在任意匹配文件判定。
    """
    if not _is_glob_pattern(generates):
        return (change_dir / generates).is_file()
    return any(Path(p).is_file() for p in glob.glob(str(change_dir / generates), recursive=True))


def _detect_completed(change_dir: Path, schema: Dict[str, Any]) -> Set[str]:
    if not change_dir.is_dir():
        return set()
    return {
        artifact["id"]
        for artifact in schema["artifacts"]
        if _artifact_output_exists(change_dir, artifact["generates"])
    }


def _get_next_artifacts(schema: Dict[str, Any], completed: Set[str]) -> Set[str]:
    """全部依赖已完成且自身未完成的 artifact（可立即创建）。"""
    return {
        artifact["id"]
        for artifact in schema["artifacts"]
        if artifact["id"] not in completed
        and all(req in completed for req in artifact.get("requires", []))
    }


def _get_blocked(schema: Dict[str, Any], completed: Set[str]) -> Dict[str, List[str]]:
    """返回 blocked artifact 与其未完成依赖（missingDeps，排序稳定）。"""
    blocked: Dict[str, List[str]] = {}
    for artifact in schema["artifacts"]:
        if artifact["id"] in completed:
            continue
        unmet = sorted(req for req in artifact.get("requires", []) if req not in completed)
        if unmet:
            blocked[artifact["id"]] = unmet
    return blocked


def _get_build_order(schema: Dict[str, Any]) -> List[str]:
    """Kahn 拓扑排序，拓扑排序输出确定性（与上游 vendored schema 的 getBuildOrder 一致）。"""
    in_degree = {a["id"]: len(a.get("requires", [])) for a in schema["artifacts"]}
    dependents: Dict[str, List[str]] = {a["id"]: [] for a in schema["artifacts"]}
    for artifact in schema["artifacts"]:
        for req in artifact.get("requires", []):
            if req not in in_degree:
                # 悬空 requires（指向未声明 artifact）：跳过建边，依赖永不满足、
                # artifact 不入拓扑序，与 _get_blocked 的 blocked 语义一致而非 KeyError。
                continue
            dependents[req].append(artifact["id"])

    queue = sorted(aid for aid, deg in in_degree.items() if deg == 0)
    result: List[str] = []
    while queue:
        current = queue.pop(0)
        result.append(current)
        newly_ready = []
        for dep in dependents[current]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                newly_ready.append(dep)
        queue.extend(sorted(newly_ready))
    if len(result) != len(in_degree):
        # 含环依赖时环内 artifact 永不入队，输出残缺拓扑序；仅告警不抛错（vendored schema 无环）。
        _LOGGER.warning(
            "Dependency cycle in schema '%s': artifacts never reachable in "
            "build order: %s",
            schema.get("name", DEFAULT_SCHEMA),
            sorted(set(in_degree) - set(result)),
        )
    return result


def status(project_root: Path, name: str) -> Dict[str, Any]:
    """计算 change 的 artifact 完成状态，输出状态 JSON（与上游 vendored schema 的 `status --json` 同构）。

    Raises:
        ValueError: 名称非 kebab-case，或 change 不存在。
    """
    # 与 new_change 同口径校验（code-review item d708be010937）：name 未校验即拼
    # 路径，含 ../ 时 change_dir 可越出项目根。
    error = _validate_name(name)
    if error:
        raise ValueError(error)

    change_dir = project_root / "spec" / "changes" / name
    if not change_dir.is_dir():
        raise ValueError(f"Change '{name}' not found at {change_dir}")

    schema = load_schema()
    completed = _detect_completed(change_dir, schema)
    ready = _get_next_artifacts(schema, completed)
    blocked = _get_blocked(schema, completed)

    artifacts = []
    for artifact in schema["artifacts"]:
        if artifact["id"] in completed:
            artifacts.append(
                {
                    "id": artifact["id"],
                    "outputPath": artifact["generates"],
                    "status": "done",
                }
            )
        elif artifact["id"] in ready:
            artifacts.append(
                {
                    "id": artifact["id"],
                    "outputPath": artifact["generates"],
                    "status": "ready",
                }
            )
        else:
            artifacts.append(
                {
                    "id": artifact["id"],
                    "outputPath": artifact["generates"],
                    "status": "blocked",
                    "missingDeps": blocked.get(artifact["id"], []),
                }
            )

    build_order = _get_build_order(schema)
    order_map = {aid: idx for idx, aid in enumerate(build_order)}
    # 回退值取 len(build_order) 而非 0（code-review item 482caa99457a）：悬空
    # requires/环依赖 artifact 不入拓扑序，回退 0 会与首位 artifact 同键、排序
    # 后窜到列表最前——回退末位序号使其排在所有可拓扑排序的 artifact 之后。
    artifacts.sort(key=lambda a: order_map.get(a["id"], len(build_order)))

    apply = schema.get("apply") or {}
    # 显式判空（code-review item c75680ee1793）：requires: [] 是「无前置」的
    # 合法声明，`or` 回退会因空列表 falsy 把语义误扩为全部 artifact 前置。
    reqs = apply.get("requires")
    apply_requires = reqs if reqs is not None else [a["id"] for a in schema["artifacts"]]

    return {
        "changeName": name,
        "schemaName": schema.get("name", DEFAULT_SCHEMA),
        "isComplete": len(completed) == len(schema["artifacts"]),
        "applyRequires": apply_requires,
        "artifacts": artifacts,
    }


# ── instructions 解析 ──────────────────────────────────────────────


def _artifact_by_id(schema: Dict[str, Any], artifact_id: str) -> Optional[Dict[str, Any]]:
    return next((a for a in schema["artifacts"] if a["id"] == artifact_id), None)


def instructions(project_root: Path, artifact_id: str, name: str) -> Dict[str, Any]:
    """返回指定 artifact 的生成指引（模板 + 指令 + 依赖信息）。

    Raises:
        ValueError: 名称非 kebab-case，change 不存在或 artifact 不在 schema 中。
    """
    # 与 new_change 同口径校验（code-review item d708be010937）：name 未校验即拼
    # 路径，含 ../ 时 change_dir 可越出项目根。
    error = _validate_name(name)
    if error:
        raise ValueError(error)

    change_dir = project_root / "spec" / "changes" / name
    if not change_dir.is_dir():
        raise ValueError(f"Change '{name}' not found at {change_dir}")

    schema = load_schema()
    schema_name = schema.get("name", DEFAULT_SCHEMA)
    artifact = _artifact_by_id(schema, artifact_id)
    if not artifact:
        raise ValueError(f"Artifact '{artifact_id}' not found in schema '{schema_name}'")

    template = _load_template(artifact["template"])
    completed = _detect_completed(change_dir, schema)

    dependencies = []
    for req in artifact.get("requires", []):
        dep = _artifact_by_id(schema, req)
        dependencies.append(
            {
                "id": req,
                "done": req in completed,
                "path": dep["generates"] if dep else req,
                "description": dep.get("description", "") if dep else "",
            }
        )

    unlocks = sorted(a["id"] for a in schema["artifacts"] if artifact_id in a.get("requires", []))

    return {
        "changeName": name,
        "artifactId": artifact_id,
        "schemaName": schema_name,
        "changeDir": str(change_dir.resolve()),
        "outputPath": artifact["generates"],
        "description": artifact.get("description", ""),
        "instruction": artifact.get("instruction", ""),
        "template": template,
        "dependencies": dependencies,
        "unlocks": unlocks,
    }
