#!/usr/bin/env python3
"""
scripts/verify_post.py の再試行上限ロジック（verify_one_pending）と
scripts/notify_chatwork.py のChatwork通知接続を検証する機械テスト。
Zernio API・S3・macOS通知・Chatwork通知はすべてmockし、ネットワークに一切依存しない。

使用方法:
  .venv/bin/python -m unittest scripts/test_verify_retry.py -v
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).parent))

import verify_post  # noqa: E402
import notify_chatwork  # noqa: E402


class VerifyOnePendingRetryTests(unittest.TestCase):
    def setUp(self):
        self.s3_client = MagicMock()
        self.bucket = "test-bucket"
        self.config = {"s3_bucket_name": self.bucket, "zernio_account_id": "acc1"}
        self.zernio_api_key = "dummy-key"
        self.key = "verification/pending/p1.json"

    def _run(self, pending, post, dry_run=False, delete_post_code=200):
        with patch.object(verify_post, "read_pending", return_value=pending) as m_read, \
             patch.object(verify_post, "get_post", return_value=post) as m_get_post, \
             patch.object(verify_post, "retry_post", return_value="new-post-id") as m_retry, \
             patch.object(verify_post, "write_pending", return_value="verification/pending/new-post-id.json") as m_write, \
             patch.object(verify_post, "delete_pending") as m_delete, \
             patch.object(verify_post, "notify", return_value=True) as m_notify, \
             patch.object(verify_post, "delete_post", return_value=delete_post_code) as m_delete_post:
            rc = verify_post.verify_one_pending(
                self.s3_client, self.bucket, self.key, self.config, self.zernio_api_key, dry_run
            )
        return rc, m_read, m_get_post, m_retry, m_write, m_delete, m_notify, m_delete_post

    # 1. 旧形式pending（ep_number等なし）＋status=failed
    #    → retry_postが1回呼ばれ、write_pendingが retry_count=1 で呼ばれる
    def test_legacy_pending_failed_retries_with_retry_count_1(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
        }
        post = {"status": "failed", "_id": "p1", "publishAttempts": 1}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

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

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

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

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

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

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

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

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

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

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_retry.assert_not_called()
        m_write.assert_not_called()
        m_delete.assert_called_once_with(self.s3_client, self.bucket, self.key)
        self.assertEqual(rc, 0)

    # 7. failed＋retry_count=0 → notifyが1回・本文に retry 1/3 と ep番号を含む
    def test_notify_called_once_on_retry_with_ep_number(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {
            "status": "failed",
            "_id": "p1",
            "publishAttempts": 1,
            "errorMessage": "media download failed",
        }

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_notify.assert_called_once()
        (message,), _ = m_notify.call_args
        self.assertIn("retry 1/3", message)
        self.assertIn("ep65", message)
        self.assertEqual(rc, 1)

    # 8. retry_count=3 → notifyが1回・本文に 再試行上限到達 を含む・retry_postは呼ばれない
    def test_notify_called_once_on_give_up(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 3,
            "original_post_id": "p0",
        }
        post = {
            "status": "failed",
            "_id": "p1",
            "publishAttempts": 4,
            "errorMessage": "media download failed",
        }

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_retry.assert_not_called()
        m_notify.assert_called_once()
        (message,), _ = m_notify.call_args
        self.assertIn("再試行上限到達", message)
        self.assertEqual(rc, 2)

    # 9. published → notifyが呼ばれない
    def test_notify_not_called_on_published(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
        }
        post = {"status": "published", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_notify.assert_not_called()
        self.assertEqual(rc, 0)

    # 10. dry_run=True＋failed → notifyが呼ばれない
    def test_notify_not_called_on_dry_run(self):
        pending = {
            "post_id": "p1",
            "scheduled_iso": "2026-08-17T20:00:00+09:00",
            "created_at": "2026-08-17T19:00:00+09:00",
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "failed", "_id": "p1", "publishAttempts": 1}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post, dry_run=True)

        m_notify.assert_not_called()
        self.assertEqual(rc, 1)

    # 12. scheduled・予定時刻から4h経過・retry_count=0
    #     → delete_postが1回、retry_postが1回、write_pendingがretry_count=1、旧pending削除、
    #       notify 1回（本文に「取消し再予約」）、rc=1
    def test_stale_deletes_old_post_and_reposts(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=4)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "scheduled", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(
            pending, post, delete_post_code=200
        )

        m_delete_post.assert_called_once_with(self.zernio_api_key, "p1")
        m_retry.assert_called_once_with(post, self.config, self.zernio_api_key)
        _, kwargs = m_write.call_args
        self.assertEqual(kwargs["retry_count"], 1)
        m_delete.assert_called_once_with(self.s3_client, self.bucket, self.key)
        m_notify.assert_called_once()
        (message,), _ = m_notify.call_args
        self.assertIn("取消し再予約", message)
        self.assertEqual(rc, 1)

    # 13. 同条件でdelete_postが400 → retry_post呼ばれない・delete_pending呼ばれない・
    #     notify 1回（本文に「取消失敗」）、rc=1
    def test_stale_delete_post_failure_does_not_repost(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=4)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "scheduled", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(
            pending, post, delete_post_code=400
        )

        m_delete_post.assert_called_once_with(self.zernio_api_key, "p1")
        m_retry.assert_not_called()
        m_delete.assert_not_called()
        m_notify.assert_called_once()
        (message,), _ = m_notify.call_args
        self.assertIn("取消失敗", message)
        self.assertEqual(rc, 1)

    # 14. scheduled・4h経過・retry_count=3 → delete_postもretry_postも呼ばれない・
    #     rc=2・notify 1回（上限到達）
    def test_stale_retry_count_3_gives_up(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=4)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
            "ep_number": 65,
            "retry_count": 3,
            "original_post_id": "p0",
        }
        post = {"status": "scheduled", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_delete_post.assert_not_called()
        m_retry.assert_not_called()
        m_notify.assert_called_once()
        (message,), _ = m_notify.call_args
        self.assertIn("再試行上限到達", message)
        self.assertEqual(rc, 2)

    # 15. scheduled・予定時刻から2h経過 → 何も呼ばれない・rc=0（STALE=3hの境界確認）
    def test_stale_within_3h_does_nothing(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=2)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "scheduled", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(pending, post)

        m_delete_post.assert_not_called()
        m_retry.assert_not_called()
        m_delete.assert_not_called()
        m_notify.assert_not_called()
        self.assertEqual(rc, 0)

    # 16. dry_run・4h経過 → delete_post呼ばれない・notify呼ばれない・rc=1
    def test_stale_dry_run_does_not_delete_or_notify(self):
        from datetime import timedelta

        scheduled_iso = (verify_post.datetime.now(verify_post.JST) - timedelta(hours=4)).isoformat()
        pending = {
            "post_id": "p1",
            "scheduled_iso": scheduled_iso,
            "created_at": scheduled_iso,
            "ep_number": 65,
            "retry_count": 0,
            "original_post_id": "p1",
        }
        post = {"status": "scheduled", "_id": "p1"}

        rc, _, _, m_retry, m_write, m_delete, m_notify, m_delete_post = self._run(
            pending, post, dry_run=True
        )

        m_delete_post.assert_not_called()
        m_notify.assert_not_called()
        self.assertEqual(rc, 1)


class NotifyChatworkEnvVarTests(unittest.TestCase):
    # 11. notify_chatwork の環境変数経路：ARTEMIS_CONFIG_JSON に chatwork キー入りJSONを入れた状態で
    #     requests.post をmockし、[toall] 付き本文でPOSTされること
    def test_env_var_config_posts_with_toall_prefix(self):
        cfg = {
            "chatwork_api_token": "dummy-token",
            "chatwork_room_id": "12345",
            "chatwork_to": "toall",
        }
        env = {"ARTEMIS_CONFIG_JSON": json.dumps(cfg)}
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch.dict(os.environ, env, clear=False), \
             patch.object(notify_chatwork, "requests") as m_requests, \
             patch.object(notify_chatwork, "_log"):
            m_requests.post.return_value = mock_resp
            ok = notify_chatwork.notify("テスト本文")

        self.assertTrue(ok)
        m_requests.post.assert_called_once()
        _, kwargs = m_requests.post.call_args
        self.assertTrue(kwargs["data"]["body"].startswith("[toall]\n"))
        self.assertIn("テスト本文", kwargs["data"]["body"])
        self.assertEqual(kwargs["headers"]["X-ChatWorkToken"], "dummy-token")
        self.assertIn("12345", m_requests.post.call_args[0][0])


class ZernioRequestRetryTests(unittest.TestCase):
    # 17. get_post：1回目 ReadTimeout→2回目 200 → 結果が返り、request呼び出し2回・sleep 1回（2秒）
    def test_get_post_retries_on_read_timeout_then_succeeds(self):
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"post": {"_id": "p1", "status": "published"}}
        mock_resp_ok.raise_for_status.return_value = None

        with patch.object(
            verify_post.requests,
            "request",
            side_effect=[requests.exceptions.ReadTimeout("timeout"), mock_resp_ok],
        ) as m_request, patch.object(verify_post.time, "sleep") as m_sleep:
            result = verify_post.get_post("dummy-key", "p1")

        self.assertEqual(result, {"_id": "p1", "status": "published"})
        self.assertEqual(m_request.call_count, 2)
        m_sleep.assert_called_once_with(2)

    # 18. get_post：3回とも ReadTimeout → 例外送出・request呼び出し3回・sleep 2回（2秒・4秒）
    def test_get_post_raises_after_three_read_timeouts(self):
        with patch.object(
            verify_post.requests,
            "request",
            side_effect=[
                requests.exceptions.ReadTimeout("t1"),
                requests.exceptions.ReadTimeout("t2"),
                requests.exceptions.ReadTimeout("t3"),
            ],
        ) as m_request, patch.object(verify_post.time, "sleep") as m_sleep:
            with self.assertRaises(requests.exceptions.ReadTimeout):
                verify_post.get_post("dummy-key", "p1")

        self.assertEqual(m_request.call_count, 3)
        self.assertEqual(m_sleep.call_count, 2)
        m_sleep.assert_any_call(2)
        m_sleep.assert_any_call(4)

    # 19. get_post：1回目 HTTP 503→2回目 200 → 結果が返る（5xxリトライ）
    def test_get_post_retries_on_http_503_then_succeeds(self):
        mock_resp_503 = MagicMock()
        mock_resp_503.status_code = 503
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"post": {"_id": "p1", "status": "published"}}
        mock_resp_ok.raise_for_status.return_value = None

        with patch.object(
            verify_post.requests, "request", side_effect=[mock_resp_503, mock_resp_ok]
        ) as m_request, patch.object(verify_post.time, "sleep") as m_sleep:
            result = verify_post.get_post("dummy-key", "p1")

        self.assertEqual(result, {"_id": "p1", "status": "published"})
        self.assertEqual(m_request.call_count, 2)
        m_sleep.assert_called_once_with(2)

    # 20. get_post：HTTP 404 → リトライせず即座に扱われる（request呼び出し1回）
    def test_get_post_404_does_not_retry(self):
        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404
        mock_resp_404.raise_for_status.side_effect = requests.exceptions.HTTPError("404")

        with patch.object(
            verify_post.requests, "request", return_value=mock_resp_404
        ) as m_request, patch.object(verify_post.time, "sleep") as m_sleep:
            with self.assertRaises(requests.exceptions.HTTPError):
                verify_post.get_post("dummy-key", "p1")

        self.assertEqual(m_request.call_count, 1)
        m_sleep.assert_not_called()

    # 21. delete_post：1回目 ConnectionError→2回目 200 → 200が返る
    def test_delete_post_retries_on_connection_error_then_succeeds(self):
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200

        with patch.object(
            verify_post.requests,
            "request",
            side_effect=[requests.exceptions.ConnectionError("conn"), mock_resp_ok],
        ) as m_request, patch.object(verify_post.time, "sleep") as m_sleep:
            code = verify_post.delete_post("dummy-key", "p1")

        self.assertEqual(code, 200)
        self.assertEqual(m_request.call_count, 2)
        m_sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
