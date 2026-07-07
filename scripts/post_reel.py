#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Instagram Reels 予約投稿スクリプト（Zernio API + S3 署名付き URL 方式）

使用方法:
  python scripts/post_reel.py <ep_number>

例:
  python scripts/post_reel.py 3

前提:
  pip install requests boto3

config.json に以下のキーが必要:
  zernio_api_key,
  aws_access_key_id, aws_secret_access_key, s3_bucket_name, s3_region
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

import boto3
import requests
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
CONFIG_PATH = Path.home() / "artemis-media/自動取得システム/config.json"
OUTPUT_BASE = Path(__file__).resolve().parent.parent / "output/instagram"
JST = timezone(timedelta(hours=9))

GITHUB_OWNER = "utack369"
GITHUB_REPO = "artemis-condori"
GITHUB_BRANCH = "main"

SCHEDULED_HOUR = 20
SCHEDULED_MINUTE = 0

MIN_SCHEDULE_OFFSET_MIN = 10

# S3 署名付き URL の有効期限（秒）
PRESIGNED_URL_EXPIRY = 86400

ZERNIO_API_BASE = "https://zernio.com/api/v1"


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
def get_scheduled_iso() -> str:
    """
    当日 20:00 JST を ISO 8601 形式で返す。すでに 20:00 を過ぎていれば翌日 20:00 JST。
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
            f"最短 {MIN_SCHEDULE_OFFSET_MIN} 分後が必要です。"
        )

    return target.isoformat()


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
# サムネイル URL
# ---------------------------------------------------------------------------
def get_thumbnail_raw_url(ep_num: int, thumb_path: Path) -> str:
    """
    GitHub raw URL を生成する。
    前提: /push N が先に実行済みで thumbnail_N.png が main ブランチに存在すること。
    """
    return (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/{GITHUB_BRANCH}/output/instagram/ep{ep_num}/{thumb_path.name}"
    )


# ---------------------------------------------------------------------------
# Zernio API 投稿
# ---------------------------------------------------------------------------
def post_to_zernio(
    zernio_api_key: str,
    account_id: str,
    video_url: str,
    caption: str,
    scheduled_iso: str,
    thumbnail_url: Optional[str] = None,
) -> str:
    """Zernio API に予約投稿リクエストを送信し、post._id を返す。"""
    endpoint = f"{ZERNIO_API_BASE}/posts"
    headers = {
        "Authorization": f"Bearer {zernio_api_key}",
        "Content-Type": "application/json",
    }
    platform_specific: dict = {
        "contentType": "reels",
        "shareToFeed": True,
    }
    if thumbnail_url:
        platform_specific["instagramThumbnail"] = thumbnail_url

    payload: dict = {
        "platforms": [
            {
                "platform": "instagram",
                "accountId": account_id,
                "platformSpecificData": platform_specific,
            }
        ],
        "content": caption,
        "mediaItems": [{"url": video_url, "type": "video"}],
        "scheduledFor": scheduled_iso,
    }

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    try:
        print(f"[DEBUG] Zernio API Response ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    except requests.HTTPError:
        raise RuntimeError(
            f"Zernio API エラー (HTTP {resp.status_code}): {resp.text}"
        ) from None

    data = resp.json()
    post_id = data.get("post", {}).get("_id")
    if not post_id:
        raise RuntimeError(f"投稿ID が取得できませんでした: {data}")
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
    zernio_api_key: str = config["zernio_api_key"]
    bucket: str = config["s3_bucket_name"]

    # S3 クライアント
    s3_client = build_s3_client(config)

    # エピソードファイル
    video_path, thumb_path, caption = get_episode_files(ep_num)

    # 予約時刻（ISO 8601）
    scheduled_iso = get_scheduled_iso()
    scheduled_jst = datetime.fromisoformat(scheduled_iso).strftime("%Y-%m-%d %H:%M JST")

    print(f"\n{'='*52}")
    print(f"  ep{ep_num} Reels 予約投稿（Zernio API）")
    print(f"{'='*52}")
    print(f"動画    : {video_path.name}")
    thumbnail_url: Optional[str] = None
    if thumb_path:
        thumbnail_url = get_thumbnail_raw_url(ep_num, thumb_path)
        print(f"サムネ  : {thumb_path.name}")
        print(f"          {thumbnail_url}")
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

        # Step 3: Zernio API に予約投稿
        print("\nStep 3: Zernio API 予約投稿")
        post_id = post_to_zernio(
            zernio_api_key,
            config["zernio_account_id"],
            presigned_url,
            caption,
            scheduled_iso,
            thumbnail_url,
        )

        print(f"\n{'='*52}")
        print(f"  予約投稿完了!")
        print(f"  投稿ID  : {post_id}")
        print(f"  公開予定: {scheduled_jst}")
        print(f"{'='*52}\n")

    finally:
        pass


if __name__ == "__main__":
    main()
