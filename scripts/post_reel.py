#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Instagram Reels 予約投稿スクリプト（Zernio API + S3 署名付き URL 方式）

使用方法:
  python scripts/post_reel.py <ep_number> [--check-only]

例:
  python scripts/post_reel.py 3
  python scripts/post_reel.py 3 --check-only  # Step 0通過確認のみ・実投稿/予約なし

前提:
  pip install requests boto3

config.json に以下のキーが必要:
  zernio_api_key,
  aws_access_key_id, aws_secret_access_key, s3_bucket_name, s3_region
"""

import json
import re
import subprocess
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
PRESIGNED_URL_EXPIRY = 604800  # 7日。クラウド検死cronの翌夜以降の再試行が24時間では失効するため（v49決定）

ZERNIO_API_BASE = "https://zernio.com/api/v1"

# クラウド検死用 pending の S3 プレフィックス（verify_post.py と共通）
PENDING_PREFIX = "verification/pending/"

# schedule_verify_job() の pending 登録リトライ設定
PENDING_PUT_MAX_ATTEMPTS = 3
PENDING_PUT_RETRY_DELAYS = [1, 2]  # 秒。attempt1失敗後1秒、attempt2失敗後2秒待って再試行

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
    """署名付き URL（有効期限 PRESIGNED_URL_EXPIRY 秒）を生成して返す。"""
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


def find_existing_pending(s3_client, bucket: str, ep_num: int) -> list[dict]:
    """verification/pending/ を列挙し、ep_number == ep_num の pending を返す（旧形式＝ep_number無しは対象外）。"""
    resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=PENDING_PREFIX)
    matches: list[dict] = []
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        if not key.endswith(".json"):
            continue
        body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        pending = json.loads(body)
        if pending.get("ep_number") == ep_num:
            matches.append(pending)
    return matches


# ---------------------------------------------------------------------------
# メディア URL 到達性チェック
# ---------------------------------------------------------------------------
def check_media_url(url: str, label: str) -> bool:
    """
    メディア URL への到達性を確認する。
    HEAD は使わない（SigV2 署名 URL は HEAD で 403 になるため）。
    """
    resp = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=30, stream=True)
    status = resp.status_code
    if status in (200, 206):
        print(f"  ✓ {label} URL到達性OK ({status})")
        return True
    print(f"  ✗ {label} URLに到達できません (HTTP {status})。Zernio登録を中止します")
    return False


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
# 検死ジョブ登録（切り離しプロセス方式）
# ---------------------------------------------------------------------------
def schedule_verify_job(post_id: str, scheduled_dt: datetime, ep_num: int) -> None:
    """
    S3 に pending ファイルを書き込み、検死（公開確認・再試行）をクラウド（GitHub Actions の
    verify_post ワークフロー）に委譲する。put_object は最大 PENDING_PUT_MAX_ATTEMPTS 回
    （PENDING_PUT_RETRY_DELAYS 間隔）再試行する。全回失敗した場合、Zernio 予約自体は
    成立済み（検死対象から漏れる）であることを明示して sys.exit(1) する。
    """
    config = load_config()
    scheduled_iso = scheduled_dt.isoformat()
    pending_key = f"{PENDING_PREFIX}{post_id}.json"
    payload = {
        "post_id": post_id,
        "scheduled_iso": scheduled_iso,
        "created_at": datetime.now(JST).isoformat(),
        "ep_number": ep_num,
        "retry_count": 0,
        "original_post_id": post_id,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    s3_client = build_s3_client(config)

    last_error: Optional[Exception] = None
    for attempt in range(PENDING_PUT_MAX_ATTEMPTS):
        try:
            s3_client.put_object(
                Bucket=config["s3_bucket_name"],
                Key=pending_key,
                Body=body,
                ContentType="application/json",
            )
            print(f"  ✓ クラウド検死用 pending 登録: s3://{config['s3_bucket_name']}/{pending_key}")
            print("  ✓ 検死はクラウド（GitHub Actions run）に委譲")
            return
        except Exception as e:
            last_error = e
            if attempt < len(PENDING_PUT_RETRY_DELAYS):
                time.sleep(PENDING_PUT_RETRY_DELAYS[attempt])

    print(
        f"✗ pending登録に{PENDING_PUT_MAX_ATTEMPTS}回失敗"
        f"（Zernio予約は成立済み・検死対象から漏れます）: {last_error}",
        file=sys.stderr,
    )
    print(
        f"  post_id={post_id} ep={ep_num} scheduled_iso={scheduled_iso} "
        f"pending_key={pending_key}",
        file=sys.stderr,
    )
    print("  → 手動登録が必要です（本部へ報告）", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# ログマスキング
# ---------------------------------------------------------------------------
def mask_signed_urls(text: str) -> str:
    """署名付きURLの認証クエリパラメータ（X-Amz-*等）をマスクして返す。"""
    return re.sub(r"(X-Amz-[A-Za-z-]+|AWSAccessKeyId|Signature)=[^&\s\"']+", r"\1=***", text)


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
        print(f"[DEBUG] Zernio API Response ({resp.status_code}): {mask_signed_urls(resp.text)}")
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
    argv = sys.argv[1:]
    check_only = "--check-only" in argv
    force = "--force" in argv
    positional = [a for a in argv if a not in ("--check-only", "--force")]

    if not positional:
        print(
            "使用方法: python scripts/post_reel.py <ep_number> [--check-only] [--force]",
            file=sys.stderr,
        )
        sys.exit(1)

    ep_num = int(positional[0])
    project_root = Path(__file__).resolve().parent.parent

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
        # Step 0: サムネイルの origin/main 反映確認
        if thumb_path:
            print("Step 0: サムネイル origin/main 反映確認")
            subprocess.run(
                ["git", "fetch", "origin", GITHUB_BRANCH],
                cwd=project_root,
                check=True,
            )
            rel_path = f"output/instagram/ep{ep_num}/{thumb_path.name}"
            result = subprocess.run(
                ["git", "ls-tree", f"origin/{GITHUB_BRANCH}", "--", rel_path],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            if not result.stdout.strip():
                print(
                    "  ✗ サムネイルがorigin/mainに存在しません。"
                    "/push を実行してから再度お試しください"
                )
                sys.exit(1)
            print(f"  ✓ サムネイルはorigin/mainに存在します: {rel_path}")
        else:
            print("Step 0: サムネイルなし（origin/main反映確認をスキップ）")

        if check_only:
            print(
                "\n--check-only: Step 0 のチェックを通過しました。"
                "実投稿・予約には進まず終了します。"
            )
            sys.exit(0)

        # 二重実行ガード（同一epのpendingが既に存在する場合は中止）
        try:
            existing_pending = find_existing_pending(s3_client, bucket, ep_num)
        except Exception as e:
            print(f"✗ pending照会に失敗（ガード判定不能）: {e}", file=sys.stderr)
            sys.exit(1)

        if existing_pending:
            pending_lines = "\n".join(
                f"   - post_id={p.get('post_id')} scheduled_iso={p.get('scheduled_iso')} "
                f"retry_count={p.get('retry_count')}"
                for p in existing_pending
            )
            if force:
                print(f"⚠ --force により続行:\n{pending_lines}")
            else:
                print(
                    f"✗ ep{ep_num} の pending が既に存在します（二重投稿防止のため中止）:\n"
                    f"{pending_lines}\n"
                    f"  再投稿が本当に必要な場合は --force を付けて実行してください。"
                )
                sys.exit(1)

        # Step 1: S3 に動画をアップロード
        print("Step 1: S3 へ動画アップロード")
        s3_key = upload_to_s3(s3_client, bucket, video_path, ep_num)

        # Step 2: 署名付き URL を生成
        print("\nStep 2: 署名付き URL 生成")
        presigned_url = generate_presigned_url(s3_client, bucket, s3_key)
        print(f"  有効期限: {PRESIGNED_URL_EXPIRY // 86400} 日")

        # Step 2.5: メディア URL 到達性チェック
        print("\nStep 2.5: メディア URL 到達性チェック")
        if not check_media_url(presigned_url, "動画"):
            sys.exit(1)
        if thumbnail_url:
            if not check_media_url(thumbnail_url, "サムネイル"):
                sys.exit(1)

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

        # Step 4: 検死ジョブ登録
        print("\nStep 4: 検死ジョブ登録")
        schedule_verify_job(post_id, datetime.fromisoformat(scheduled_iso), ep_num)

        print(f"\n{'='*52}")
        print(f"  予約投稿完了!")
        print(f"  投稿ID  : {post_id}")
        print(f"  公開予定: {scheduled_jst}")
        print(f"{'='*52}\n")

    finally:
        pass


if __name__ == "__main__":
    main()
