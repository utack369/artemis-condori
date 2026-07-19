#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Zernio 投稿 検死・自動再試行スクリプト（post_reel.py の投稿後チェック用）

使用方法:
  ローカル（従来方式・挙動無変更）:
    python scripts/verify_post.py <zernio_post_id> [--dry-run]
  クラウド（GitHub Actions 用）:
    python scripts/verify_post.py --from-s3 [--dry-run]

--from-s3 モード:
  S3 の verification/pending/ 配下にある pending ファイルを全件検死する。
    - published              → 公開確認 OK。pending を削除
    - scheduled（24h 未満）  → 時刻前/処理中とみなし pending を保持（翌回再チェック）
    - scheduled（24h 以上）  → 滞留として exit 1（要通知）
    - failed                 → 自動再試行し、新 post_id の pending を登録。exit 1（要通知）
    - 未知ステータス         → exit 1（要通知）
  exit 1 は GitHub Actions の run 失敗となり、GitHub からメール通知される。

前提:
  post_reel.py と同じ config.json（同じパス・同じキー名）を使用する。
"""

import argparse
import json
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

# クラウド検死（--from-s3）用
PENDING_PREFIX = "verification/pending/"
STALE_SCHEDULED_HOURS = 24


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
    """macOS 通知。osascript が無い環境（CI ランナー等）では何もしない。"""
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            check=False,
        )
    except Exception:
        pass


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
# ステータス別ハンドラ（ローカルモード・従来挙動）
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
# S3 pending ファイル操作（クラウドモード用）
# ---------------------------------------------------------------------------
def list_pending(s3_client, bucket: str) -> list:
    """verification/pending/ 配下の pending ファイルのキー一覧を返す。"""
    resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=PENDING_PREFIX)
    return [
        obj["Key"]
        for obj in resp.get("Contents", [])
        if obj["Key"].endswith(".json")
    ]


def read_pending(s3_client, bucket: str, key: str) -> dict:
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body)


def write_pending(s3_client, bucket: str, post_id: str, scheduled_iso: str) -> str:
    """pending ファイルを登録し、S3 キーを返す（再試行後の新 post_id 用）。"""
    key = f"{PENDING_PREFIX}{post_id}.json"
    payload = {
        "post_id": post_id,
        "scheduled_iso": scheduled_iso,
        "created_at": datetime.now(JST).isoformat(),
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def delete_pending(s3_client, bucket: str, key: str) -> None:
    s3_client.delete_object(Bucket=bucket, Key=key)


# ---------------------------------------------------------------------------
# クラウドモード（--from-s3）
# ---------------------------------------------------------------------------
def verify_one_pending(
    s3_client, bucket: str, key: str, config: dict, zernio_api_key: str, dry_run: bool
) -> int:
    """pending 1 件を検死する。0=正常、1=要通知（run 失敗にする）。"""
    pending = read_pending(s3_client, bucket, key)
    post_id = pending["post_id"]

    post = get_post(zernio_api_key, post_id)
    status = post.get("status")
    log(post_id, status)

    if status == "published":
        print("✓ 公開確認 OK")
        if dry_run:
            print("[dry-run] pending 削除をスキップ")
        else:
            delete_pending(s3_client, bucket, key)
            print(f"✓ pending 削除: {key}")
        return 0

    if status == "scheduled":
        scheduled_iso = pending.get("scheduled_iso")
        if scheduled_iso:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_iso)
                elapsed = datetime.now(JST) - scheduled_dt
                if elapsed > timedelta(hours=STALE_SCHEDULED_HOURS):
                    print(
                        f"✗ scheduled のまま {STALE_SCHEDULED_HOURS} 時間以上滞留"
                        f"（予定時刻: {scheduled_iso}）"
                    )
                    return 1
            except ValueError:
                print(f"⚠ scheduled_iso を解釈できません: {scheduled_iso}")
        print("△ まだ公開時刻前または処理中（pending 保持・翌回再チェック）")
        return 0

    if status == "failed":
        print(f"✗ 投稿失敗を検出: {extract_error_message(post)}")
        if dry_run:
            print("[dry-run] 再スケジュールをスキップ")
            return 1
        new_post_id = retry_post(post, config, zernio_api_key)
        print(f"✓ 再登録完了: 新規投稿ID={new_post_id}")
        new_key = write_pending(s3_client, bucket, new_post_id, get_retry_scheduled_iso())
        print(f"✓ 再試行分の pending 登録: {new_key}")
        delete_pending(s3_client, bucket, key)
        print(f"✓ 旧 pending 削除: {key}")
        return 1  # 再試行が発生した事実を通知するため run は失敗扱いにする

    print(f"△ 未知のステータス: {status}")
    return 1


def main_from_s3(dry_run: bool) -> int:
    config = load_config()
    zernio_api_key: str = config["zernio_api_key"]
    bucket: str = config["s3_bucket_name"]
    s3_client = build_s3_client(config)

    keys = list_pending(s3_client, bucket)
    if not keys:
        print("pending なし（検死対象はありません）")
        return 0

    print(f"pending {len(keys)} 件を検死します")
    worst = 0
    for key in keys:
        print(f"--- {key} ---")
        try:
            rc = verify_one_pending(s3_client, bucket, key, config, zernio_api_key, dry_run)
        except Exception as e:
            print(f"✗ 検死処理エラー ({key}): {e}", file=sys.stderr)
            rc = 1
        worst = max(worst, rc)
    return worst


# ---------------------------------------------------------------------------
# ローカルモード（従来方式・挙動無変更）
# ---------------------------------------------------------------------------
def run_local(post_id: str, dry_run: bool) -> int:
    config = load_config()
    zernio_api_key: str = config["zernio_api_key"]

    post = get_post(zernio_api_key, post_id)
    status = post.get("status")
    log(post_id, status)

    if status == "published":
        print("✓ 公開確認 OK")
        return 0

    if status == "scheduled":
        print("△ まだ公開時刻前または処理中")
        return 0

    if status == "failed":
        return handle_failed(post, config, zernio_api_key, dry_run)

    print(f"△ 未知のステータス: {status}")
    return 0


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("post_id", nargs="?", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-s3", action="store_true")
    args = parser.parse_args()

    if args.from_s3 == (args.post_id is not None):
        parser.error("post_id か --from-s3 のどちらか一方を指定してください")

    if args.from_s3:
        sys.exit(main_from_s3(args.dry_run))

    sys.exit(run_local(args.post_id, args.dry_run))


if __name__ == "__main__":
    main()
