"""``core.evolution.clear_todo`` 单元测试（自省内容清理原语）。

覆盖：正常截断 / 文件缺失不建目录 / 幂等 / 仅动 todo.md 不碰自进化数据 /
与标记回写共用同一把锁（同进程串行，不互相覆盖）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.evolution import (  # noqa: E402
    clear_todo, write_todo_marker, upsert_item, read_items,
)

TODO_BODY = (
    "## 2026-09-14\n\n### 浪费\n"
    "- **问题甲**\n"
    "  - 影响：i\n  - 证据：e\n  - 调查评估：a\n  - 建议：s\n\n"
    "### 可改进\n- （当日无）\n"
)


def _proj(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / ".fenix").mkdir(parents=True)
    (proj / ".fenix" / "todo.md").write_text(TODO_BODY, encoding="utf-8")
    return proj


class TestClearTodo:
    def test_truncates_existing_file(self, tmp_path):
        proj = _proj(tmp_path)
        result = clear_todo(proj)
        assert result["ok"] is True
        assert result["existed"] is True
        assert result["error"] is None
        todo = proj / ".fenix" / "todo.md"
        # 保留文件本体（非删除），内容为空
        assert todo.is_file()
        assert todo.read_text(encoding="utf-8") == ""

    def test_missing_file_is_noop_and_creates_nothing(self, tmp_path):
        proj = tmp_path / "empty-proj"
        result = clear_todo(proj)
        assert result["ok"] is True
        assert result["existed"] is False
        # MUST NOT 替无 todo 的项目凭空创建 .fenix/
        assert not (proj / ".fenix").exists()

    def test_idempotent_on_already_empty(self, tmp_path):
        proj = _proj(tmp_path)
        clear_todo(proj)
        second = clear_todo(proj)
        assert second["ok"] is True
        assert second["existed"] is True
        assert (proj / ".fenix" / "todo.md").read_text(encoding="utf-8") == ""

    def test_leaves_evolution_data_untouched(self, tmp_path):
        proj = _proj(tmp_path)
        rec = {"id": "x1", "project": "proj", "date_section": "2026-09-14",
               "section": "浪费", "title": "问题甲", "status": "pending"}
        upsert_item(proj, rec)
        clear_todo(proj)
        # 清空范围仅限 todo.md：items.jsonl 原样保留
        assert read_items(proj)["x1"]["title"] == "问题甲"
        assert (proj / ".fenix" / "todo.md").read_text(encoding="utf-8") == ""

    def test_marker_writeback_after_clear_degrades_gracefully(self, tmp_path):
        """清空后标记回写找不到条目 → 返回 False 且不重建内容、不抛异常。"""
        proj = _proj(tmp_path)
        clear_todo(proj)
        item = {"project": "proj", "date_section": "2026-09-14",
                "section": "浪费", "title": "问题甲"}
        assert write_todo_marker(item, project_path=proj) is False
        assert (proj / ".fenix" / "todo.md").read_text(encoding="utf-8") == ""

    def test_shares_lock_with_marker_writeback(self, tmp_path):
        """与 write_todo_marker 共用同一把锁文件：两写者交替后文件始终完整。

        清空 → 次日自省重新追加 → 标记回写仍能命中；再清空则标记随之消失，
        不留半截内容。
        """
        proj = _proj(tmp_path)
        item = {"project": "proj", "date_section": "2026-09-14",
                "section": "浪费", "title": "问题甲"}
        assert clear_todo(proj)["ok"] is True
        # 次日自省重新追加（self_review._append_todo 走同一把锁）
        (proj / ".fenix" / "todo.md").write_text(TODO_BODY, encoding="utf-8")
        assert write_todo_marker(item, project_path=proj) is True
        assert "自进化：" in (proj / ".fenix" / "todo.md").read_text(
            encoding="utf-8")
        assert clear_todo(proj)["ok"] is True
        assert (proj / ".fenix" / "todo.md").read_text(encoding="utf-8") == ""
        # 锁文件命名与 self_review 共用（<目录>/.<文件名>.lock）
        assert (proj / ".fenix" / ".todo.md.lock").exists()
