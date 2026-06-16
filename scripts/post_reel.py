#!/usr/bin/env python3
"""
Instagram Reels 予約投稿スクリプト（Resumable Upload 方式）

使用方法:
  python scripts/post_reel.py <ep_number>

例:
  python scripts/post_reel.py 3

前提:
  pip install requests
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

import requests

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

    # サムネイル（情報表示のみ。Resumable Upload は動画専用のため upload 不可）
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


def create_resumable_container(
    ig_user_id: str,
    access_token: str,
    caption: str,
    scheduled_ts: int,
    cover_url: Optional[str] = None,
) -> Tuple[str, str]:
    """
    upload_type=resumable でメディアコンテナを作成し、(container_id, upload_uri) を返す。

    video_url は指定しない。動画バイナリはレスポンスの uri に直接 POST する。
    caption・scheduled_publish_time・cover_url はこのステップで確定させる。
    """
    endpoint = f"{IG_API_BASE}/{ig_user_id}/media"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "media_type": "REELS",
        "upload_type": "resumable",
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
    upload_uri = data.get("uri")
    if not container_id or not upload_uri:
        raise RuntimeError(f"コンテナ作成失敗（id または uri が欠落）: {data}")
    return container_id, upload_uri


def upload_video_resumable(
    upload_uri: str,
    access_token: str,
    video_path: Path,
    timeout: int = 600,
) -> None:
    """
    rupload.facebook.com に動画バイナリをストリーミング送信する。

    ヘッダー:
      Authorization: OAuth（Bearer ではなく OAuth が rupload の正式仕様）
      offset    : 0（先頭から送信 = 再開なしの単発アップロード）
      file_size : ファイルのバイト数（正確に一致させる必要がある）
      Content-Length: file_size と同値（サーバーが受信量を検証するために必要）

    ファイルオブジェクトを data= に渡すことでメモリに全展開せずストリーミング送信する。
    """
    file_size = video_path.stat().st_size
    size_mb = file_size / 1024 / 1024
    print(f"  ファイル: {video_path.name} ({size_mb:.1f} MB)")
    print(f"  送信先 : {upload_uri}")

    headers = {
        "Authorization": f"OAuth {access_token}",
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_size),
    }

    with open(video_path, "rb") as f:
        resp = requests.post(
            upload_uri,
            headers=headers,
            data=f,
            timeout=timeout,
        )

    _raise_for_api_error(resp)
    print("  アップロード完了")


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

    # エピソードファイル
    video_path, thumb_path, caption = get_episode_files(ep_num)

    # 予約時刻
    scheduled_ts = get_scheduled_timestamp()
    scheduled_jst = datetime.fromtimestamp(scheduled_ts, JST).strftime(
        "%Y-%m-%d %H:%M JST"
    )

    print(f"\n{'='*52}")
    print(f"  ep{ep_num} Reels 予約投稿（Resumable Upload）")
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

    # Step 1: コンテナ作成（upload_type=resumable）
    print("Step 1: メディアコンテナ作成")
    container_id, upload_uri = create_resumable_container(
        ig_user_id, access_token, caption, scheduled_ts, cover_url
    )
    print(f"  コンテナID     : {container_id}")
    print(f"  アップロードURI: {upload_uri}")

    # Step 2: 動画バイナリを rupload.facebook.com に直送
    print("\nStep 2: 動画アップロード（rupload.facebook.com）")
    upload_video_resumable(upload_uri, access_token, video_path)

    # Step 3: Meta 側のエンコード完了を待機
    print("\nStep 3: コンテナ処理待機")
    wait_for_container_ready(access_token, container_id)

    # Step 4: 予約投稿登録
    print("\nStep 4: 予約投稿登録")
    post_id = publish_reel(ig_user_id, access_token, container_id)

    print(f"\n{'='*52}")
    print(f"  予約投稿完了!")
    print(f"  投稿ID  : {post_id}")
    print(f"  公開予定: {scheduled_jst}")
    print(f"{'='*52}\n")


if __name__ == "__main__":
    main()
