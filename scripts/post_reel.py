#!/usr/bin/env python3
"""
Instagram Reels 予約投稿スクリプト（S3 署名付き URL 方式）

使用方法:
  python scripts/post_reel.py <ep_number>

例:
  python scripts/post_reel.py 3

前提:
  pip install requests boto3

config.json に以下のキーが必要:
  access_token, ig_user_id,
  aws_access_key_id, aws_secret_access_key, s3_bucket_name, s3_region
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

import boto3
import requests
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
CONFIG_PATH = Path.home() / "Downloads/コンドリ/自動取得システム/config.json"
OUTPUT_BASE = Path(__file__).resolve().parent.parent / "output/instagram"
API_VERSION = "v20.0"
IG_API_BASE = f"https://graph.facebook.com/{API_VERSION}"
JST = timezone(timedelta(hours=9))

GITHUB_OWNER = "utack369"
GITHUB_REPO = "artemis-condori"
GITHUB_BRANCH = "main"

SCHEDULED_HOUR = 20
SCHEDULED_MINUTE = 0

# Meta API の制約: 最短10分後・最長75日後
MIN_SCHEDULE_OFFSET_MIN = 10

# S3 署名付き URL の有効期限（秒）
PRESIGNED_URL_EXPIRY = 3600


# ---------------------------------------------------------------------------
# 設定読み込み
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# エピソードファイル取得
# ---------------------------------------------------------------------------
def get_episode_files(ep_num: int) -> Tuple[Path, Optional[Path], str]:
    """
    output/instagram/ep<N>/ から動画・サムネイル・キャプションを取得する。

    優先順位:
      動画    : *.mp4（複数あれば辞書順で最初）
      サムネ  : thumbnail_N.png > thumbnail_N.jpg
      キャプ  : caption_N.txt > caption.md
    """
    ep_dir = OUTPUT_BASE / f"ep{ep_num}"
    if not ep_dir.exists():
        raise FileNotFoundError(f"エピソードフォルダが見つかりません: {ep_dir}")

    # MP4
    mp4_files = sorted(ep_dir.glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError(f"MP4ファイルが見つかりません: {ep_dir}")
    video_path = mp4_files[0]

    # サムネイル
    thumb_candidates = (
        sorted(ep_dir.glob("thumbnail_*.png"))
        + sorted(ep_dir.glob("thumbnail_*.jpg"))
    )
    thumb_path: Optional[Path] = thumb_candidates[0] if thumb_candidates else None

    # キャプション
    for caption_name in [f"caption_{ep_num}.txt", "caption.md"]:
        caption_file = ep_dir / caption_name
        if caption_file.exists():
            return video_path, thumb_path, caption_file.read_text(encoding="utf-8").strip()

    raise FileNotFoundError(f"キャプションファイルが見つかりません: {ep_dir}")


# ---------------------------------------------------------------------------
# 予約時刻計算
# ---------------------------------------------------------------------------
def get_scheduled_timestamp() -> int:
    """
    当日 20:00 JST を返す。すでに 20:00 を過ぎていれば翌日 20:00 JST。
    Meta API の制約（最短10分後）を確認する。
    """
    now = datetime.now(JST)
    target = now.replace(
        hour=SCHEDULED_HOUR, minute=SCHEDULED_MINUTE, second=0, microsecond=0
    )
    if now >= target:
        target += timedelta(days=1)

    diff_min = (target - now).total_seconds() / 60
    if diff_min < MIN_SCHEDULE_OFFSET_MIN:
        raise ValueError(
            f"予約時刻が近すぎます（{diff_min:.1f}分後）。"
            f"Meta API は最短 {MIN_SCHEDULE_OFFSET_MIN} 分後が必要です。"
        )

    return int(target.timestamp())


# ---------------------------------------------------------------------------
# S3 操作
# ---------------------------------------------------------------------------
def build_s3_client(config: dict):
    return boto3.client(
        "s3",
        region_name=config["s3_region"],
        aws_access_key_id=config["aws_access_key_id"],
        aws_secret_access_key=config["aws_secret_access_key"],
    )


def upload_to_s3(s3_client, bucket: str, video_path: Path, ep_num: int) -> str:
    """動画を S3 にアップロードし、S3 キーを返す。"""
    s3_key = f"reels/{ep_num}/{video_path.name}"
    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"  ファイル: {video_path.name} ({size_mb:.1f} MB)")
    print(f"  S3キー  : s3://{bucket}/{s3_key}")

    s3_client.upload_file(
        str(video_path),
        bucket,
        s3_key,
        ExtraArgs={"ContentType": "video/mp4"},
    )
    print("  アップロード完了")
    return s3_key


def generate_presigned_url(s3_client, bucket: str, s3_key: str) -> str:
    """署名付き URL（有効期限 1 時間）を生成して返す。"""
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    return url


def delete_from_s3(s3_client, bucket: str, s3_key: str) -> None:
    """S3 から動画ファイルを削除する。"""
    try:
        s3_client.delete_object(Bucket=bucket, Key=s3_key)
        print(f"  S3削除完了: {s3_key}")
    except ClientError as e:
        print(f"  S3削除失敗（無視して続行）: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Meta / Instagram Graph API 操作
# ---------------------------------------------------------------------------
def _raise_for_api_error(resp: requests.Response) -> None:
    """Meta API のエラーレスポンスを人間が読めるメッセージで raise する"""
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        try:
            err = resp.json().get("error", {})
            msg = err.get("message", resp.text)
            code = err.get("code", "?")
            fbtrace = err.get("fbtrace_id", "")
            raise RuntimeError(
                f"Meta API エラー (code={code}, fbtrace={fbtrace}): {msg}"
            ) from None
        except (ValueError, KeyError):
            raise RuntimeError(
                f"HTTP エラー {resp.status_code}: {resp.text}"
            ) from None


def get_thumbnail_raw_url(ep_num: int, thumb_path: Path) -> str:
    """
    GitHub raw URL を生成する。
    前提: /push N が先に実行済みで thumbnail_N.png が main ブランチに存在すること。
    """
    return (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/{GITHUB_BRANCH}/output/instagram/ep{ep_num}/{thumb_path.name}"
    )


def create_video_url_container(
    ig_user_id: str,
    access_token: str,
    video_url: str,
    caption: str,
    scheduled_ts: int,
    cover_url: Optional[str] = None,
) -> str:
    """
    video_url パラメータでメディアコンテナを作成し、container_id を返す。
    """
    endpoint = f"{IG_API_BASE}/{ig_user_id}/media"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "published": False,
        "scheduled_publish_time": str(scheduled_ts),
    }
    if cover_url:
        payload["cover_url"] = cover_url

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    _raise_for_api_error(resp)

    data = resp.json()
    container_id = data.get("id")
    if not container_id:
        raise RuntimeError(f"コンテナ作成失敗（id が欠落）: {data}")
    return container_id


def wait_for_container_ready(
    access_token: str,
    container_id: str,
    max_wait_sec: int = 300,
    poll_interval_sec: int = 10,
) -> None:
    """
    コンテナの status_code が FINISHED になるまでポーリングする。
    Meta 側でのエンコード完了まで最大 5 分待機する。
    """
    endpoint = f"{IG_API_BASE}/{container_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"fields": "status_code,status"}

    print("  処理中", end="", flush=True)
    elapsed = 0
    status = ""
    while elapsed < max_wait_sec:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=30)
        _raise_for_api_error(resp)
        data = resp.json()
        status = data.get("status_code", "")

        if status == "FINISHED":
            print(" → 完了")
            return
        if status == "ERROR":
            raise RuntimeError(f"コンテナ処理エラー: {data.get('status', data)}")

        print(".", end="", flush=True)
        time.sleep(poll_interval_sec)
        elapsed += poll_interval_sec

    raise TimeoutError(
        f"コンテナが {max_wait_sec} 秒以内に完了しませんでした"
        f"（最後のステータス: {status}）"
    )


def publish_reel(ig_user_id: str, access_token: str, container_id: str) -> str:
    """
    コンテナを media_publish し、投稿 ID を返す。
    scheduled_publish_time 設定済みのコンテナは指定時刻に自動公開される。
    """
    endpoint = f"{IG_API_BASE}/{ig_user_id}/media_publish"
    headers = {"Authorization": f"OAuth {access_token}"}
    payload = {"creation_id": container_id}

    resp = requests.post(endpoint, headers=headers, data=payload, timeout=60)
    _raise_for_api_error(resp)

    post_id = resp.json().get("id")
    if not post_id:
        raise RuntimeError(f"公開失敗: {resp.json()}")
    return post_id


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------
def main() -> None:
    if len(sys.argv) < 2:
        print("使用方法: python scripts/post_reel.py <ep_number>", file=sys.stderr)
        sys.exit(1)

    ep_num = int(sys.argv[1])

    # 設定
    config = load_config()
    access_token: str = config["access_token"]
    ig_user_id: str = config["ig_user_id"]
    bucket: str = config["s3_bucket_name"]

    # S3 クライアント
    s3_client = build_s3_client(config)

    # エピソードファイル
    video_path, thumb_path, caption = get_episode_files(ep_num)

    # 予約時刻
    scheduled_ts = get_scheduled_timestamp()
    scheduled_jst = datetime.fromtimestamp(scheduled_ts, JST).strftime(
        "%Y-%m-%d %H:%M JST"
    )

    print(f"\n{'='*52}")
    print(f"  ep{ep_num} Reels 予約投稿（S3 署名付き URL）")
    print(f"{'='*52}")
    print(f"動画    : {video_path.name}")
    cover_url: Optional[str] = None
    if thumb_path:
        cover_url = get_thumbnail_raw_url(ep_num, thumb_path)
        print(f"サムネ  : {thumb_path.name}")
        print(f"          {cover_url}")
    print(f"公開予定: {scheduled_jst}")
    print(f"キャプ  : {caption[:60]}{'...' if len(caption) > 60 else ''}")
    print()

    s3_key: Optional[str] = None
    try:
        # Step 1: S3 に動画をアップロード
        print("Step 1: S3 へ動画アップロード")
        s3_key = upload_to_s3(s3_client, bucket, video_path, ep_num)

        # Step 2: 署名付き URL を生成
        print("\nStep 2: 署名付き URL 生成")
        presigned_url = generate_presigned_url(s3_client, bucket, s3_key)
        print(f"  有効期限: {PRESIGNED_URL_EXPIRY // 60} 分")

        # Step 3: メディアコンテナ作成（video_url 方式）
        print("\nStep 3: メディアコンテナ作成")
        container_id = create_video_url_container(
            ig_user_id, access_token, presigned_url, caption, scheduled_ts, cover_url
        )
        print(f"  コンテナID: {container_id}")

        # Step 4: Meta 側のエンコード完了を待機
        print("\nStep 4: コンテナ処理待機")
        wait_for_container_ready(access_token, container_id)

        # Step 5: 予約投稿登録
        print("\nStep 5: 予約投稿登録")
        post_id = publish_reel(ig_user_id, access_token, container_id)

        print(f"\n{'='*52}")
        print(f"  予約投稿完了!")
        print(f"  投稿ID  : {post_id}")
        print(f"  公開予定: {scheduled_jst}")
        print(f"{'='*52}\n")

    finally:
        # S3 から動画を削除（成功・失敗問わず）
        if s3_key:
            print("\nCleanup: S3 から動画を削除")
            delete_from_s3(s3_client, bucket, s3_key)


if __name__ == "__main__":
    main()
