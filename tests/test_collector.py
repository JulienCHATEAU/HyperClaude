"""Tests du socle de collecte (L0).

Utilisent uniquement la stdlib (``unittest``, ``tempfile``, ``unittest.mock``) : aucun
outil externe requis. Executent la logique de parsing/tri/mapping sur des fixtures, sans
dependre des vraies sessions Claude Code de la machine.

    python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hyperclaude import collector  # noqa: E402


def _write_session(dir_path, pid, **fields):
    payload = {"pid": pid, **fields}
    (Path(dir_path) / f"{pid}.json").write_text(json.dumps(payload), encoding="utf-8")


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_parse_and_defaults(self):
        _write_session(self.tmp, 111, sessionId="abc", name="repo-x", cwd="/tmp", status="busy")
        entry = collector._parse_session_file(self.tmp / "111.json")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.pid, 111)
        self.assertEqual(entry.session_id, "abc")
        self.assertEqual(entry.status, "busy")
        self.assertIsNone(entry.waiting_for)

    def test_unknown_status_is_normalized(self):
        _write_session(self.tmp, 222, status="bogus")
        entry = collector._parse_session_file(self.tmp / "222.json")
        self.assertEqual(entry.status, "unknown")

    def test_non_integer_filename_is_ignored(self):
        (self.tmp / "not-a-pid.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(collector._parse_session_file(self.tmp / "not-a-pid.json"))

    def test_corrupt_json_is_ignored(self):
        (self.tmp / "333.json").write_text("{ this is not json", encoding="utf-8")
        self.assertIsNone(collector._parse_session_file(self.tmp / "333.json"))


class CollectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_collect_sorts_and_filters(self):
        _write_session(self.tmp, 1, name="idle-one", status="idle")
        _write_session(self.tmp, 2, name="waiting-one", status="waiting", waitingFor="permission prompt")
        _write_session(self.tmp, 3, name="busy-one", status="busy")
        _write_session(self.tmp, 4, name="dead-one", status="idle")

        ps_map = {1: (10, "ttys001"), 2: (20, "ttys002"), 3: (30, "ttys003"), 4: (40, "ttys004")}
        with mock.patch.object(collector, "SESSIONS_DIR", self.tmp), \
             mock.patch.object(collector, "_pid_alive", lambda pid: pid != 4), \
             mock.patch.object(collector, "_build_ps_map", lambda: ps_map):
            entries = collector.collect(now_ms=0)

        # Le mort est exclu.
        self.assertEqual([e.pid for e in entries], [2, 3, 1])
        # Tri : waiting -> busy -> idle.
        self.assertEqual([e.status for e in entries], ["waiting", "busy", "idle"])
        # Mapping tty + shell_pid (ppid) + focusable.
        self.assertEqual(entries[0].tty, "ttys002")
        self.assertEqual(entries[0].shell_pid, 20)
        self.assertTrue(all(e.focusable for e in entries))
        self.assertEqual(entries[0].waiting_for, "permission prompt")

    def test_include_dead(self):
        _write_session(self.tmp, 5, name="dead", status="idle")
        with mock.patch.object(collector, "SESSIONS_DIR", self.tmp), \
             mock.patch.object(collector, "_pid_alive", lambda pid: False), \
             mock.patch.object(collector, "_build_ps_map", lambda: {}):
            self.assertEqual(collector.collect(), [])
            included = collector.collect(include_dead=True)

        self.assertEqual([e.pid for e in included], [5])
        self.assertFalse(included[0].alive)
        self.assertFalse(included[0].focusable)  # aucun tty resolu

    def test_stale_flag(self):
        # updated_at tres ancien vs now_ms -> stale, mais toujours retourne.
        _write_session(self.tmp, 6, name="old", status="idle", updatedAt=1)
        with mock.patch.object(collector, "SESSIONS_DIR", self.tmp), \
             mock.patch.object(collector, "_pid_alive", lambda pid: True), \
             mock.patch.object(collector, "_build_ps_map", lambda: {6: (60, "ttys006")}):
            entries = collector.collect(now_ms=collector.STALE_AFTER_MS + 1000)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].stale)


class AiTitleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_last_ai_title(self):
        log = self.tmp / "sess.jsonl"
        lines = [
            '{"type":"ai-title","aiTitle":"Ancien titre","sessionId":"s"}',
            '{"type":"user","message":"..."}',
            '{"type":"ai-title","aiTitle":"Titre courant","sessionId":"s"}',
            '{"type":"assistant","message":"..."}',
        ]
        log.write_text("\n".join(lines), encoding="utf-8")
        self.assertEqual(collector._read_ai_title(log), "Titre courant")

    def test_no_title_returns_none(self):
        log = self.tmp / "sess.jsonl"
        log.write_text('{"type":"user"}\n{"type":"assistant"}', encoding="utf-8")
        self.assertIsNone(collector._read_ai_title(log))

    def test_falls_back_to_last_prompt(self):
        log = self.tmp / "sess.jsonl"
        lines = [
            '{"type":"last-prompt","lastPrompt":"Premier","sessionId":"s"}',
            '{"type":"last-prompt","lastPrompt":"Ping","sessionId":"s"}',
        ]
        log.write_text("\n".join(lines), encoding="utf-8")
        self.assertEqual(collector._read_ai_title(log), "Ping")


class TtyResolutionTests(unittest.TestCase):
    def test_resolve_tty_direct(self):
        ps_map = {100: (90, "ttys010")}
        self.assertEqual(collector._resolve_tty(100, ps_map), "ttys010")

    def test_resolve_tty_walks_up_to_parent(self):
        # Le process 'claude' (100) n'a pas de tty direct, mais son shell parent (90) si.
        ps_map = {100: (90, "??"), 90: (1, "ttys009")}
        self.assertEqual(collector._resolve_tty(100, ps_map), "ttys009")

    def test_resolve_tty_none_when_detached(self):
        ps_map = {100: (90, "??"), 90: (1, "??")}
        self.assertIsNone(collector._resolve_tty(100, ps_map))


if __name__ == "__main__":
    unittest.main()
