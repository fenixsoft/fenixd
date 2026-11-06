"""add-spec-chinese-title task 1.3：SPEC 中文标题读取与透传单测。

覆盖：
1. read_spec_title 容错矩阵（活跃有/无 title、归档有/无 title、文件缺失、
   字段缺失、YAML 损坏、非法 spec 名 → 一律 None，不抛异常）
2. 活跃优先：活跃与归档目录并存时读活跃侧
3. archive_dir_map 单次扫描映射语义（剥日期前缀、exact 优先、后缀候选、
   sorted 兜底、墓碑登记、归档根缺失 → 空）
4. spec_summary / spec_detail 透传形状（有值 string / 缺失 null；
   SummaryIndex 归档路径经 archive_dirs 下发读取）
5. 签名缓存：改写 .spec.yaml 后 mtime/size 变化自然失效，读到新值
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.dashboard.data.spec_docs import (
    archive_dir_map,
    read_spec_title,
)
from core.dashboard.data.summary import spec_summary, spec_detail

ACTIVE_TITLE = "知识收件箱回填管线"


def _make_active(root: Path, name: str, yaml_text: str | None) -> Path:
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    if yaml_text is not None:
        (d / ".spec.yaml").write_text(yaml_text, encoding="utf-8")
    return d


def _make_archive(root: Path, dirname: str, yaml_text: str | None) -> Path:
    d = root / "spec" / "archive" / dirname
    d.mkdir(parents=True, exist_ok=True)
    if yaml_text is not None:
        (d / ".spec.yaml").write_text(yaml_text, encoding="utf-8")
    return d


class TestReadSpecTitle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_active_with_title(self):
        _make_active(self.root, "add-knowledge-inbox-pipeline",
                     "schema: spec-driven\ncreated: 2026-11-01\ntitle: 知识收件箱回填管线\n")
        self.assertEqual(
            read_spec_title(self.root, "add-knowledge-inbox-pipeline"), ACTIVE_TITLE
        )

    def test_active_without_title_field(self):
        # 存量 spec：无 title 字段 → None（零迁移）
        _make_active(self.root, "add-legacy", "schema: spec-driven\ncreated: 2026-09-02\n")
        self.assertIsNone(read_spec_title(self.root, "add-legacy"))

    def test_active_file_missing(self):
        _make_active(self.root, "bare", None)
        self.assertIsNone(read_spec_title(self.root, "bare"))

    def test_spec_dir_missing(self):
        self.assertIsNone(read_spec_title(self.root, "ghost"))

    def test_yaml_corrupted(self):
        _make_active(self.root, "broken",
                     "schema: spec-driven\ncreated: [unclosed\n  bad:: ::\n")
        self.assertIsNone(read_spec_title(self.root, "broken"))

    def test_title_non_string_or_blank(self):
        _make_active(self.root, "num", "title: 12345\n")
        _make_active(self.root, "blank", "title: '   '\n")
        self.assertIsNone(read_spec_title(self.root, "num"))
        self.assertIsNone(read_spec_title(self.root, "blank"))

    def test_invalid_spec_names(self):
        for bad in ("../evil", "a/b", None, 42, "", ".."):
            with self.subTest(bad=bad):
                self.assertIsNone(read_spec_title(self.root, bad))

    def test_archive_fallback_via_resolve(self):
        # 活跃缺失 → resolve_spec_dir 归档回退（非索引路径缺省行为）
        _make_archive(self.root, "2026-09-09-add-spec-archive",
                      "schema: spec-driven\ncreated: 2026-09-09\ntitle: 归档目录自动提交\n")
        self.assertEqual(read_spec_title(self.root, "add-spec-archive"), "归档目录自动提交")

    def test_archive_fallback_via_map(self):
        # 索引路径：archive_dirs 查表（缺表项 → None，不做归档解析）
        _make_archive(self.root, "2026-09-09-add-spec-archive",
                      "schema: spec-driven\ncreated: 2026-09-09\ntitle: 归档目录自动提交\n")
        amap = archive_dir_map(self.root)
        self.assertEqual(
            read_spec_title(self.root, "add-spec-archive", archive_dirs=amap),
            "归档目录自动提交",
        )
        self.assertIsNone(read_spec_title(self.root, "add-spec-archive", archive_dirs={}))

    def test_active_wins_over_archive(self):
        # 活跃目录存在 → 只读活跃侧（resolve_spec_dir 活跃优先同语义）
        _make_active(self.root, "dual", "title: 活跃标题\n")
        _make_archive(self.root, "2026-09-01-dual", "title: 归档标题\n")
        self.assertEqual(read_spec_title(self.root, "dual"), "活跃标题")

    def test_archive_without_title(self):
        _make_archive(self.root, "2026-09-01-notitled", "schema: spec-driven\n")
        self.assertIsNone(read_spec_title(self.root, "notitled"))
        self.assertIsNone(read_spec_title(self.root, "notitled", archive_dirs={}))

    def test_signature_cache_invalidation(self):
        p = _make_active(self.root, "cache", "title: 旧标题\n")
        self.assertEqual(read_spec_title(self.root, "cache"), "旧标题")
        # 同长度改写 + 显式 distinct mtime_ns：签名变化必须自然失效
        p.joinpath(".spec.yaml").write_text("title: 新标题\n", encoding="utf-8")
        os.utime(p.joinpath(".spec.yaml"), ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(read_spec_title(self.root, "cache"), "新标题")


class TestArchiveDirMap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_archive_root(self):
        self.assertEqual(archive_dir_map(self.root), {})

    def test_date_prefix_stripped(self):
        _make_archive(self.root, "2026-09-09-add-spec-archive", None)
        amap = archive_dir_map(self.root)
        self.assertEqual(
            amap.get("add-spec-archive"),
            self.root / "spec" / "archive" / "2026-09-09-add-spec-archive",
        )

    def test_exact_priority_independent_spec_coexist(self):
        # evo-foo 与 evo-foo-2 并存：查 evo-foo 必须 exact 命中自己的目录
        foo = _make_archive(self.root, "2026-09-01-evo-foo", None)
        foo2 = _make_archive(self.root, "2026-09-02-evo-foo-2", None)
        amap = archive_dir_map(self.root)
        self.assertEqual(amap.get("evo-foo"), foo)
        self.assertEqual(amap.get("evo-foo-2"), foo2)

    def test_suffix_candidate_fallback(self):
        # 仅冲突后缀目录（同日二次归档）时，剥后缀基名仍可命中
        _make_archive(self.root, "2026-09-01-add-foo-1", None)
        amap = archive_dir_map(self.root)
        self.assertEqual(
            amap.get("add-foo"),
            self.root / "spec" / "archive" / "2026-09-01-add-foo-1",
        )

    def test_latest_date_wins(self):
        # 同层多命中取 sorted()[-1]（日期最新）
        _make_archive(self.root, "2026-09-01-add-bar", None)
        latest = _make_archive(self.root, "2026-09-15-add-bar", None)
        self.assertEqual(archive_dir_map(self.root).get("add-bar"), latest)

    def test_tombstone_registered(self):
        # 软删除墓碑（无日期前缀）按全等名登记
        tomb = _make_archive(self.root, "del-spec", None)
        self.assertEqual(archive_dir_map(self.root).get("del-spec"), tomb)


class TestSummaryPassthrough(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_summary_title_string_and_null(self):
        _make_active(self.root, "with-title", "title: 知识收件箱回填管线\n")
        _make_active(self.root, "no-title", "schema: spec-driven\n")
        s1 = spec_summary(self.root, "with-title", {"status": "drafted"})
        self.assertEqual(s1["title"], ACTIVE_TITLE)
        s2 = spec_summary(self.root, "no-title", {"status": "drafted"})
        self.assertIsNone(s2["title"])

    def test_summary_archived_entry_via_map(self):
        # 已归档条目：活跃目录缺失，经 archive_dirs 下发读取（SummaryIndex 链）
        _make_archive(self.root, "2026-09-09-add-spec-archive",
                      "schema: spec-driven\ncreated: 2026-09-09\ntitle: 归档目录自动提交\n")
        amap = archive_dir_map(self.root)
        s = spec_summary(
            self.root, "add-spec-archive", {"status": "archived"},
            archived_entries={"add-spec-archive": {"status": "archived"}},
            archive_dirs=amap,
        )
        self.assertEqual(s["title"], "归档目录自动提交")
        self.assertTrue(s["archived"])

    def test_detail_title_string_and_null(self):
        _make_active(self.root, "with-title",
                     "schema: spec-driven\ntitle: 知识收件箱回填管线\n")
        s = spec_detail(self.root, "with-title", {"status": "drafted"})
        self.assertEqual(s["title"], ACTIVE_TITLE)
        _make_active(self.root, "no-title", "schema: spec-driven\n")
        s2 = spec_detail(self.root, "no-title", {"status": "drafted"})
        self.assertIsNone(s2["title"])

    def test_detail_archived_fallback(self):
        # 详情非索引路径：read_spec_title 内部经 resolve_spec_dir 回退
        _make_archive(self.root, "2026-09-09-add-spec-archive",
                      "schema: spec-driven\ntitle: 归档目录自动提交\n")
        s = spec_detail(self.root, "add-spec-archive", {"status": "archived"})
        self.assertEqual(s["title"], "归档目录自动提交")


if __name__ == "__main__":
    unittest.main()
