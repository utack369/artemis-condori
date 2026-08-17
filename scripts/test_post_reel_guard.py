#!/usr/bin/env python3
"""
scripts/post_reel.py の二重実行ガード（find_existing_pending）と
pending登録リトライ（schedule_verify_job）を検証する機械テスト。
Zernio API・S3・requestsはすべてmockし、ネットワークに一切依存しない。

使用方法:
  .venv/bin/python -m unittest scripts/test_post_reel_guard.py -v
"""

import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import post_reel  # noqa: E402


def _pending_body(pending: dict) -> dict:
    body = MagicMock()
    body.read.return_value = json.dumps(pending, ensure_ascii=False).encode("utf-8")
    return {"Body": body}


class FindExistingPendingTests(unittest.TestCase):
    def setUp(self):
        self.s3_client = MagicMock()
        self.bucket = "test-bucket"

    # 1. pending 3件（ep65／ep66／旧形式ep_number無し）→ ep_num=65で1件だけ返る
    def test_returns_only_matching_ep_number(self):
        self.s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "verification/pending/p65.json"},
                {"Key": "verification/pending/p66.json"},
                {"Key": "verification/pending/plegacy.json"},
            ]
        }
        pendings = {
            "verification/pending/p65.json": {
                "post_id": "p65", "scheduled_iso": "2026-08-17T20:00:00+09:00",
                "ep_number": 65, "retry_count": 0,
            },
            "verification/pending/p66.json": {
                "post_id": "p66", "scheduled_iso": "2026-08-17T20:00:00+09:00",
                "ep_number": 66, "retry_count": 0,
            },
            "verification/pending/plegacy.json": {
                "post_id": "plegacy", "scheduled_iso": "2026-08-17T20:00:00+09:00",
            },
        }
        self.s3_client.get_object.side_effect = (
            lambda Bucket, Key: _pending_body(pendings[Key])
        )

        result = post_reel.find_existing_pending(self.s3_client, self.bucket, 65)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["post_id"], "p65")

    # 2. 該当なし → 空リスト
    def test_returns_empty_list_when_no_match(self):
        self.s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "verification/pending/p66.json"},
            ]
        }
        self.s3_client.get_object.return_value = _pending_body(
            {"post_id": "p66", "scheduled_iso": "2026-08-17T20:00:00+09:00", "ep_number": 66}
        )

        result = post_reel.find_existing_pending(self.s3_client, self.bucket, 65)

        self.assertEqual(result, [])


class ScheduleVerifyJobRetryTests(unittest.TestCase):
    def setUp(self):
        self.config = {"s3_bucket_name": "test-bucket"}
        self.scheduled_dt = datetime.fromisoformat("2026-08-17T20:00:00+09:00")

    # 3. put_objectが2回例外→3回目成功 → 例外にならず put_object 呼び出し3回（sleepはmock）
    def test_put_object_succeeds_on_third_attempt(self):
        s3_client = MagicMock()
        s3_client.put_object.side_effect = [Exception("timeout"), Exception("timeout"), None]

        with patch.object(post_reel, "load_config", return_value=self.config), \
             patch.object(post_reel, "build_s3_client", return_value=s3_client), \
             patch.object(post_reel.time, "sleep") as m_sleep:
            post_reel.schedule_verify_job("p1", self.scheduled_dt, 65)

        self.assertEqual(s3_client.put_object.call_count, 3)
        self.assertEqual(m_sleep.call_count, 2)

    # 4. 3回とも例外 → SystemExit(1)・stderrに `pending登録に3回失敗` と post_id を含む
    def test_put_object_fails_all_three_attempts_exits_1(self):
        s3_client = MagicMock()
        s3_client.put_object.side_effect = Exception("timeout")

        with patch.object(post_reel, "load_config", return_value=self.config), \
             patch.object(post_reel, "build_s3_client", return_value=s3_client), \
             patch.object(post_reel.time, "sleep"), \
             patch("sys.stderr", new_callable=io.StringIO) as m_stderr:
            with self.assertRaises(SystemExit) as cm:
                post_reel.schedule_verify_job("p1", self.scheduled_dt, 65)

        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(s3_client.put_object.call_count, 3)
        stderr_output = m_stderr.getvalue()
        self.assertIn("pending登録に3回失敗", stderr_output)
        self.assertIn("p1", stderr_output)


if __name__ == "__main__":
    unittest.main()
