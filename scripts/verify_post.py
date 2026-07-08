#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Zernio 投稿 検死・自動再試行スクリプト（post_reel.py の投稿後チェック用）

使用方法:
  python scripts/verify_post.py <zernio_post_id> [--dry-run]

前提:
  post_reel.py と同じ config.json（同じパス・同じキー名）を使用する。
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests

from post_reel import (
    JST,
    ZERNIO_API_BASE,
    build_s3_client,
    generate_presigned_url,
    load_config,
    post_to_zernio,
)

RETRY_DELAY_MINUTES = 15


# ---------------------------------------------------------------------------
# Zernio API
# ---------------------------------------------------------------------------
def get_post(zernio_api_key: str, post_id: str) -> dict:
    endpoint = f"{ZERNIO_API_BASE}/posts/{post_id}"
    headers = {"Authorization": f"Bearer {zernio_api_key}"}
    resp = requests.get(endpoint, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["post"]


# ---------------------------------------------------------------------------
# post データ抽出
# ---------------------------------------------------------------------------
def extract_error_message(post: dict) -> Optional[str]:
    if post.get("errorMessage"):
        return post["errorMessage"]
    platforms = post.get("platforms") or []
    if platforms:
        return platforms[0].get("errorMessage")
    return None


def extract_media_url(post: dict) -> str:
    media_items = post.get("mediaItems") or []
    if not media_items:
        platforms = post.get("platforms") or []
        media_items = platforms[0].get("mediaItems") if platforms else []
    if not media_items:
        raise RuntimeError("mediaItems が見つかりません")
    return media_items[0]["url"]


def extract_thumbnail_url(post: dict) -> Optional[str]:
    platforms = post.get("platforms") or []
    if not platforms:
        return None
    return platforms[0].get("platformSpecificData", {}).get("instagramThumbnail")


def extract_s3_key(video_url: str) -> str:
    """署名付き URL から S3 キー（パス部分）を取り出す。"""
    return urlparse(video_url).path.lstrip("/")


# ---------------------------------------------------------------------------
# 通知・再スケジュール
# ---------------------------------------------------------------------------
def notify_macos(message: str, title: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
        check=False,
    )


def get_retry_scheduled_iso() -> str:
    """現在時刻 + RETRY_DELAY_MINUTES 分を ISO 8601 で返す。"""
    target = datetime.now(JST) + timedelta(minutes=RETRY_DELAY_MINUTES)
    return target.isoformat()


def retry_post(post: dict, config: dict, zernio_api_key: str) -> str:
    """既存動画を新しい署名付き URL で再登録し、新規投稿 ID を返す。"""
    video_url = extract_media_url(post)
    s3_key = extract_s3_key(video_url)

    bucket: str = config["s3_bucket_name"]
    s3_client = build_s3_client(config)
    new_presigned_url = generate_presigned_url(s3_client, bucket, s3_key)

    return post_to_zernio(
        zernio_api_key,
        config["zernio_account_id"],
        new_presigned_url,
        post.get("content", ""),
        get_retry_scheduled_iso(),
        extract_thumbnail_url(post),
    )


# ---------------------------------------------------------------------------
# ステータス別ハンドラ
# ---------------------------------------------------------------------------
def handle_failed(post: dict, config: dict, zernio_api_key: str, dry_run: bool) -> int:
    print(f"✗ 投稿失敗を検出: {extract_error_message(post)}")
    notify_macos("ep投稿がfailedです。自動再試行します", "Zernio検死")

    if dry_run:
        print("[dry-run] 再スケジュールをスキップ")
        return 2

    new_post_id = retry_post(post, config, zernio_api_key)
    print(f"✓ 再登録完了: 新規投稿ID={new_post_id}")
    return 0


def log(post_id: str, status: str) -> None:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    print(f"[{now}] post_id={post_id} status={status}")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("post_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()
    zernio_api_key: str = config["zernio_api_key"]

    post = get_post(zernio_api_key, args.post_id)
    status = post.get("status")
    log(args.post_id, status)

    if status == "published":
        print("✓ 公開確認 OK")
        sys.exit(0)

    if status == "scheduled":
        print("△ まだ公開時刻前または処理中")
        sys.exit(0)

    if status == "failed":
        sys.exit(handle_failed(post, config, zernio_api_key, args.dry_run))

    print(f"△ 未知のステータス: {status}")
    sys.exit(0)


if __name__ == "__main__":
    main()
