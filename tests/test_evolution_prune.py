"""
evo-item-retention-doc-tracking：条目保留策略（prune_items）测试。

覆盖：
- 保留并集边界（>7 天且超出 100 名被删 / 7 天内多于 100 条时旧的被删 / 阈值内零删除）
- created_at 缺失或非法时保留
- 未决状态（pending）同样被删
- 草稿目录随删除清理
- 单条删除异常不中断其余
- ok=False 的计数口径（failed 而非 deleted）
"""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core.evolution import (
    ITEM_RETENTION_DAYS,
    ITEM_RETENTION_MIN,
    delete_item,
    draft_dir,
    evolution_dir,
    prune_items,
    read_items,
    upsert_item,
    write_items,
)


class _BasePruneTest(unittest.TestCase):
    """prune_items 测试基类：临时目录 + 公共辅助。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rec(self, eid, created_at=None, status="pending"):
        """构造一条最小条目记录。"""
        rec = {
            "id": eid, "project": "proj", "date_section": "2026-09-12",
            "section": "浪费", "title": f"问题-{eid}",
            "impact": "i", "evidence": "e", "analysis": "a",
            "suggestion": "s",
            "verdict": {"worth_spec": True, "problem_exists": "yes",
                        "suggestion_sound": "yes", "rationale": "r"},
            "analysis_md": "md", "spec": None, "spec_summary": "",
            "degraded": None, "status": status,
            "created_at": created_at,
            "decided_at": None, "decided_by": None, "spec_name": None,
            "violations": None, "draft_failed_reason": None,
        }
        return rec

    def _now(self, days=0, hours=0):
        """返回当前 UTC 时间偏移指定天/小时。"""
        return datetime.now(timezone.utc) + timedelta(days=days, hours=hours)


# ── 保留并集边界 ────────────────────────────────────────────────────

class TestPruneRetentionUnion(_BasePruneTest):
    """D1：保留并集 = 最近 7 天 ∪ 最近 100 条（取较多数者）。"""

    def test_over_7_days_and_outside_100_deleted(self):
        """>7 天且在最近 100 名之外 → 被删。"""
        now = self._now()
        # 创建 120 条：20 条在 30 天前（超出 7 天），100 条在今天
        recs = []
        for i in range(100):
            recs.append(self._rec(f"new-{i:03d}",
                                  created_at=(now - timedelta(hours=i)).isoformat()))
        for i in range(20):
            recs.append(self._rec(f"old-{i:03d}",
                                  created_at=(now - timedelta(days=30)).isoformat()))
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        self.assertEqual(result["total"], 120)
        self.assertEqual(result["deleted"], 20)
        self.assertEqual(result["kept"], 100)
        self.assertEqual(result["failed"], 0)
        remaining = read_items(self.proot)
        self.assertEqual(len(remaining), 100)
        self.assertTrue(all(k.startswith("new-") for k in remaining))

    def test_within_7_days_exceeds_100_old_deleted(self):
        """最近 7 天内多于 100 条 → 旧的被删（按 7 天保留）。"""
        now = self._now()
        # 130 条在最近 7 天内（倒序前 100 保留 + 后 30 在 7 天内保留），
        # 10 条在 8 天前
        recs = []
        for i in range(130):
            recs.append(self._rec(f"recent-{i:03d}",
                                  created_at=(now - timedelta(hours=i)).isoformat()))
        for i in range(10):
            recs.append(self._rec(f"stale-{i:03d}",
                                  created_at=(now - timedelta(days=8)).isoformat()))
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        self.assertEqual(result["total"], 140)
        self.assertEqual(result["deleted"], 10)
        self.assertEqual(result["kept"], 130)
        remaining = read_items(self.proot)
        self.assertEqual(len(remaining), 130)
        self.assertFalse(any(k.startswith("stale-") for k in remaining))

    def test_within_thresholds_zero_deletes(self):
        """全部在 7 天内且 ≤100 条 → 不删除任何条目，items.jsonl 不变。"""
        now = self._now()
        recs = [self._rec(f"i-{i:02d}",
                          created_at=(now - timedelta(hours=i)).isoformat())
                for i in range(35)]
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        self.assertEqual(result["total"], 35)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["kept"], 35)
        # 文件内容不变
        self.assertEqual(len(read_items(self.proot)), 35)

    def test_empty_items_no_write(self):
        """items.jsonl 不存在 → 直接返回，不触发写。"""
        result = prune_items(self.proot, now=self._now())
        self.assertEqual(result, {"total": 0, "kept": 0, "deleted": 0,
                                  "failed": 0, "details": []})
        self.assertFalse(evolution_dir(self.proot).exists())


# ── created_at 缺失/非法保留 ────────────────────────────────────────

class TestPruneCreatedAtMissing(_BasePruneTest):
    """D3：创建时间缺失或非法 → 年龄不可知 → 保留（fail-open）。"""

    def test_missing_created_at_kept(self):
        """created_at 为 None → 保留（fail-open：年龄不可知）。"""
        now = self._now()
        recs = []
        for i in range(110):
            # 第 109 条缺 created_at（None）；其余 109 条在 30 天前
            ca = None if i == 109 else (now - timedelta(days=30)).isoformat()
            recs.append(self._rec(f"i-{i:03d}", created_at=ca))
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        # 排序：缺 created_at 的排最后（"" < timestamp），不在 top 100，
        # 但 created_at 解析失败 → 保留（fail-open）
        items = read_items(self.proot)
        self.assertIn("i-109", items, "缺 created_at 条目 MUST 被保留")
        self.assertIsNone(items["i-109"]["created_at"])
        # 其余 109 条 30 天前，前 100 保留、9 条删除
        self.assertEqual(result["deleted"], 9)

    def test_invalid_created_at_kept(self):
        """created_at 为非法字符串 → 保留。"""
        now = self._now()
        recs = [
            self._rec("good-old", created_at=(now - timedelta(days=30)).isoformat()),
            self._rec("bad-time", created_at="not-a-date"),
            self._rec("good-new", created_at=now.isoformat()),
        ]
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        items = read_items(self.proot)
        self.assertIn("bad-time", items, "非法 created_at 条目应保留")
        self.assertIn("good-new", items)
        # 3 items total → all in top 100 → no deletions
        self.assertEqual(result["deleted"], 0)


# ── 未决状态同样被删 ────────────────────────────────────────────────

class TestPrunePendingAlsoPruned(_BasePruneTest):
    """未决条目（pending/analyzed）同样受保留策略约束。"""

    def test_old_pending_deleted(self):
        """超过 7 天且不在前 100 名的 pending 条目被删。"""
        now = self._now()
        # 100 条 recent pending + 5 条 old pending → old 全部落在 top 100 之外
        recs = [
            self._rec(f"recent-{i:03d}",
                      created_at=(now - timedelta(hours=i)).isoformat(),
                      status="pending")
            for i in range(100)
        ]
        for i in range(5):
            recs.append(self._rec(f"old-{i}",
                                  created_at=(now - timedelta(days=30)).isoformat(),
                                  status="pending"))
        write_items(self.proot, recs)

        result = prune_items(self.proot, now=now)
        self.assertEqual(result["deleted"], 5)
        remaining = read_items(self.proot)
        self.assertEqual(len(remaining), 100)
        self.assertFalse(any(k.startswith("old-") for k in remaining))


# ── 草稿目录随删除清理 ──────────────────────────────────────────────

class TestPruneDraftDirCleanup(_BasePruneTest):
    """受害条目的草稿目录随 delete_item 一并删除。"""

    def test_draft_dir_deleted_with_victim(self):
        now = self._now()
        # 100 条 recent + 1 条 old victim + 1 条 old filler
        recs = [
            self._rec(f"recent-{i:03d}",
                      created_at=(now - timedelta(hours=i)).isoformat())
            for i in range(100)
        ]
        recs.append(self._rec("victim-1",
                              created_at=(now - timedelta(days=30)).isoformat()))
        recs.append(self._rec("filler-1",
                              created_at=(now - timedelta(days=31)).isoformat()))
        write_items(self.proot, recs)

        # 为 victim 建草稿目录
        victim_draft = draft_dir(self.proot, "victim-1")
        victim_draft.mkdir(parents=True)
        (victim_draft / "proposal.md").write_text("x", encoding="utf-8")

        result = prune_items(self.proot, now=now)
        self.assertEqual(result["deleted"], 2)
        self.assertFalse(victim_draft.exists(), "草稿目录应随硬删被清理")


# ── 单条删除异常不中断其余 ──────────────────────────────────────────

class TestPruneSingleFailureResilient(_BasePruneTest):
    """单条删除抛异常 → 计入 failed，不中断其余。"""

    def test_exception_does_not_stop_others(self):
        now = self._now()
        # 100 条 recent + 2 条 OLD（fail-1 / ok-1，30 天前）
        recs = [
            self._rec(f"recent-{i:03d}",
                      created_at=(now - timedelta(hours=i)).isoformat())
            for i in range(100)
        ]
        recs.append(self._rec("fail-1",
                              created_at=(now - timedelta(days=30)).isoformat()))
        recs.append(self._rec("ok-1",
                              created_at=(now - timedelta(days=30)).isoformat()))
        write_items(self.proot, recs)

        orig_delete = delete_item

        def _patched(eid, project_root, *args, **kwargs):
            # 转发剩余实参（prune_items 现以 defer_commit=True 批量删除，
            # item 15c9a7b72fbe）——替身签名与真实 delete_item 对齐
            if eid == "fail-1":
                raise OSError("模拟草稿删除失败")
            return orig_delete(eid, project_root, *args, **kwargs)

        with mock.patch("core.evolution.delete_item", side_effect=_patched):
            result = prune_items(self.proot, now=now)

        # fail-1 抛异常（failed）→ 清理继续，ok-1 仍被删
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["deleted"], 1)
        remaining = read_items(self.proot)
        self.assertIn("recent-000", remaining)
        self.assertNotIn("ok-1", remaining, "其余受害条目仍被清理")


# ── ok=False 计数口径 ───────────────────────────────────────────────

class TestPruneDeleteItemOkFalse(_BasePruneTest):
    """delete_item 返回 ok=False → 计入 failed 而非 deleted。"""

    def test_ok_false_counted_as_failed(self):
        now = self._now()
        # 100 条 recent + 2 条 OLD（v-1 草稿越界 symlink、fill-v 正常）
        recs = [
            self._rec(f"recent-{i:03d}",
                      created_at=(now - timedelta(hours=i)).isoformat())
            for i in range(100)
        ]
        recs.append(self._rec("v-1",
                              created_at=(now - timedelta(days=30)).isoformat()))
        recs.append(self._rec("fill-v",
                              created_at=(now - timedelta(days=31)).isoformat()))
        write_items(self.proot, recs)

        # v-1 的草稿目录为指向外部的 symlink → _safe_draft_dir 拒绝 → ok=False
        v1_draft = draft_dir(self.proot, "v-1")
        outside = self.proot.parent / "outside_prune"
        outside.mkdir(exist_ok=True)
        (outside / "file.txt").write_text("keep", encoding="utf-8")
        v1_draft.parent.mkdir(parents=True, exist_ok=True)
        v1_draft.symlink_to(outside, target_is_directory=True)

        result = prune_items(self.proot, now=now)
        # v-1 删除失败（ok=False，路径越界）→ failed；fill-v 正常被删 → deleted
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["deleted"], 1)
        self.assertTrue(any(d.get("id") == "v-1" for d in result["details"]))
        # v-1 仍在 items.jsonl（ok=False 不移除）
        items = read_items(self.proot)
        self.assertIn("v-1", items)
        self.assertNotIn("fill-v", items)


# ── 排序确定性 ──────────────────────────────────────────────────────

class TestPruneDeterministicOrder(_BasePruneTest):
    """等时条目按 id 排序，多次运行结果一致。"""

    def test_same_time_different_ids_deterministic(self):
        now = self._now()
        same_time = (now - timedelta(days=30)).isoformat()
        # 105 条同时间（30 天前）→ 按 id 字典序取前 100，其余 5 条被删
        recs = [self._rec(f"item-{i:03d}", created_at=same_time)
                for i in range(105)]

        # 运行 1
        write_items(self.proot, recs)
        result1 = prune_items(self.proot, now=now)
        remaining1 = sorted(read_items(self.proot).keys())

        # 重播种后运行 2（模拟下次检查点）
        write_items(self.proot, recs)
        result2 = prune_items(self.proot, now=now)
        remaining2 = sorted(read_items(self.proot).keys())

        self.assertEqual(result1["deleted"], 5)
        self.assertEqual(result2["deleted"], 5)
        self.assertEqual(remaining1, remaining2)


if __name__ == "__main__":
    unittest.main()
