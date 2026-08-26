import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_claude_log import cli


class CodexTranscriptTests(unittest.TestCase):
    def write_jsonl(self, path, entries):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))

    def test_extract_codex_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript = Path(temp_dir) / (
                "rollout-2026-08-26T10-00-00-11111111-2222-3333-4444-555555555555.jsonl"
            )
            entries = [
                {
                    "timestamp": "2026-08-26T14:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "11111111-2222-3333-4444-555555555555",
                        "cwd": "/work/example",
                        "git": {
                            "repository_url": "https://github.com/acme/example.git"
                        },
                    },
                },
                {
                    "timestamp": "2026-08-26T14:00:01.000Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "item": {
                            "type": "UserMessage",
                            "content": [{"type": "text", "text": "Fix ABC-123 login"}],
                        },
                    },
                },
                {
                    "timestamp": "2026-08-26T14:00:02.000Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "item": {
                            "type": "CommandExecution",
                            "command": [
                                "/bin/bash",
                                "-c",
                                'git commit -m "Fix login"',
                            ],
                        },
                    },
                },
                {
                    "timestamp": "2026-08-26T14:00:03.000Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "item": {
                            "type": "FileChange",
                            "changes": {"/work/example/auth.py": {"type": "update"}},
                        },
                    },
                },
                {
                    "timestamp": "2026-08-26T14:00:04.000Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "item": {
                            "type": "AgentMessage",
                            "content": "Login fixed and tests pass.",
                        },
                    },
                },
            ]
            self.write_jsonl(transcript, entries)

            session_id, title, dates = cli.extract_session(transcript)

            self.assertEqual(session_id, "11111111-2222-3333-4444-555555555555")
            self.assertEqual(title, "Fix ABC-123 login")
            day = dates["2026-08-26"]
            self.assertEqual(day["project_short"], "acme/example")
            self.assertEqual(day["user_messages"], 1)
            self.assertEqual(day["assistant_messages"], 1)
            self.assertEqual(day["tools_used"], {"Shell": 1, "FileChange": 1})
            self.assertEqual(day["commits"], ["Fix login"])
            self.assertEqual(day["jira_tickets"], ["ABC-123"])
            self.assertEqual(day["files_touched"], ["/work/example/auth.py"])

    def test_find_and_collect_codex_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = "11111111-2222-3333-4444-555555555555"
            transcript = (
                root
                / "sessions/2026/08/26"
                / (f"rollout-2026-08-26T10-00-00-{session_id}.jsonl")
            )
            self.write_jsonl(
                transcript,
                [
                    {
                        "timestamp": "2026-08-26T14:00:00.000Z",
                        "type": "session_meta",
                        "payload": {"id": session_id, "cwd": "/work/example"},
                    },
                    {
                        "timestamp": "2026-08-26T14:00:01.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "item": {
                                "type": "UserMessage",
                                "content": "Summarize this",
                            },
                        },
                    },
                ],
            )
            os.utime(transcript, None)

            with (
                patch.object(cli, "CODEX_DIR", root),
                patch.object(cli, "CLAUDE_DIR", root / "missing"),
            ):
                self.assertEqual(cli.find_session_jsonl(session_id), str(transcript))
                sessions = cli.find_all_sessions(days=1)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
