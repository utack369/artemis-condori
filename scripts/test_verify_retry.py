#!/usr/bin/env python3
"""
scripts/verify_post.py の再試行上限ロジック（verify_one_pending）を検証する機械テスト。
Zernio API・S3・macOS通知はすべてmockし、ネットワークに一切依存しない。

使用方法:
  .venv/bin/python -m unittest scripts/test_verify_retry.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import verify_post  # noqa: E402


class VerifyOnePendingRetryTests(unittest.TestCase):
    def setUp(self):
        self.s3_client = MagicMock()
        self.bucket = "test-bucket"
        self.config = {"s3_bucket_name": self.bucket, "zernio_account_id": "acc1"}
        self.zernio_api_key = "dummy-key"
        self.key = "verification/pending/p1.json"

    def _run(self, pending, post, dry_run=False):
        with patch.object(verify_post, "read_pending", return_value=pending) as m_read, \
             patch.object(verify_post, "get_post", return_value=post) as m_get_post, \
             patch.object(verify_post, "retry_post", return_value="new-post-id") as m_retry, \
             patch.object(verify_post, "write_pending", return_value="verification/pending/new-post-id.json") as m_write, \
             patch.object(verify_post, "delete_pending") as m_delete:
            rc = verify_post.verify_one_pending(
                self.s3_client, self.bucket, self.key, self.config, self.zernio_api_key, dry_run
            )
        return rc, m_read, m_get_post, m_retry, m_write, m_delete

    # 1. 旧形式pending（ep_number等なし）＋status=failed
    #    → retry_postが1回呼ばれ、write_pendingが retry_count=1 で呼ばれる
    def test_legacy_pending_failed_retries_with_retry_count_1(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
        }
        post = {"status": "failed", "_id": "p1", "publishAttempts": 1}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_called_once_with(post, self.config, self.zernio_api_key)
        m_write.assert_called_once()
        _, kwargs = m_write.call_args
        self.assertEqual(kwargs["retry_count"], 1)
        self.assertEqual(kwargs["ep_number"], None)
        self.assertEqual(kwargs["original_post_id"], "p1")
        m_delete.assert_called_once_with(self.s3_client, self.bucket, self.key)
        self.assertEqual(rc, 1)

    # 2. retry_count=2＋failed → retry呼ばれ retry_count=3 で書かれる
    def test_retry_count_2_failed_writes_retry_count_3(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 2,
            "original_post_id": "p0",
        }
        post = {"status": "failed", "_id": "p1", "publishAttempts": 3}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_called_once_with(post, self.config, self.zernio_api_key)
        _, kwargs = m_write.call_args
        self.assertEqual(kwargs["retry_count"], 3)
        self.assertEqual(kwargs["ep_number"], 65)
        self.assertEqual(kwargs["original_post_id"], "p0")
        self.assertEqual(rc, 1)

    # 3. retry_count=3＋failed → retry_postが呼ばれない・delete_pendingも呼ばれない・戻り値2
    def test_retry_count_3_failed_gives_up(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 3,
            "original_post_id": "p0",
        }
        post = {"status": "failed", "_id": "p1", "publishAttempts": 4}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_not_called()
        m_write.assert_not_called()
        m_delete.assert_not_called()
        self.assertEqual(rc, 2)

    # 4. status=publishing（予定時刻から1h後）→ 戻り値0・何も呼ばれない
    def test_publishing_within_24h_does_nothing(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=1)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
        }
        post = {"status": "publishing", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_not_called()
        m_write.assert_not_called()
        m_delete.assert_not_called()
        self.assertEqual(rc, 0)

    # 5. status=partial → failedと同じ経路
    def test_partial_follows_same_path_as_failed(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "partial", "_id": "p1", "publishAttempts": 1}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_called_once_with(post, self.config, self.zernio_api_key)
        _, kwargs = m_write.call_args
        self.assertEqual(kwargs["retry_count"], 1)
        m_delete.assert_called_once_with(self.s3_client, self.bucket, self.key)
        self.assertEqual(rc, 1)

    # 6. status=published → delete_pending呼ばれ戻り値0
    def test_published_deletes_pending(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
        }
        post = {"status": "published", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete = self._run(pending, post)

        m_retry.assert_not_called()
        m_write.assert_not_called()
        m_delete.assert_called_once_with(self.s3_client, self.bucket, self.key)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
