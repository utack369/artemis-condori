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
    - published                       → 公開確認 OK。pending を削除
    - scheduled/publishing（3h 未満）    → 時刻前/処理中とみなし pending を保持（翌回再チェック）
    - scheduled/publishing（3h 以上・retry_count < MAX_RETRY）
        → DELETE /posts/{postId} で旧予約を取消してから再予約し、
          retry_count+1 の新 pending を登録。exit 1（要通知）
    - scheduled/publishing（3h 以上・DELETE失敗）
        → 二重投稿回避のため再予約せず pending を保持。exit 1（要通知・取消失敗）
    - scheduled/publishing（3h 以上・retry_count >= MAX_RETRY）
        → 再予約せず GIVE_UP をログ出力、pending は保持。exit 2（要通知）
    - failed/partial（retry_count < MAX_RETRY） → 自動再試行し、retry_count+1 の新 pending を登録。exit 1（要通知）
    - failed/partial（retry_count >= MAX_RETRY） → 再試行せず GIVE_UP をログ出力、pending は保持。exit 2（要通知）
    - 未知ステータス                  → exit 1（要通知）
  環境変数 VERIFY_DISABLE_RETRY=1 のとき、failed/partial・滞留のいずれでも再試行/再予約せず
  pending を保持して exit 1（並走期間用）。
  exit 1・exit 2 は GitHub Actions の run 失敗となり、GitHub からメール通知される。

前提:
  post_reel.py と同じ config.json（同じパス・同じキー名）を使用する。
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional, Tuple
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
from notify_chatwork import notify

RETRY_DELAY_MINUTES = 15
MAX_RETRY = 3

# クラウド検死（--from-s3）用
PENDING_PREFIX = "verification/pending/"
STALE_SCHEDULED_HOURS = 3


# ---------------------------------------------------------------------------
# Zernio API
# ---------------------------------------------------------------------------
def get_post(zernio_api_key: str, post_id: str) -> dict:
    endpoint = f"{ZERNIO_API_BASE}/posts/{post_id}"
    headers = {"Authorization": f"Bearer {zernio_api_key}"}
    resp = requests.get(endpoint, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["post"]


def delete_post(zernio_api_key: str, post_id: str) -> int:
    """DELETE /posts/{post_id}。HTTPステータスコードを返す（例外は呼び出し側で扱う）。"""
    endpoint = f"{ZERNIO_API_BASE}/posts/{post_id}"
    headers = {"Authorization": f"Bearer {zernio_api_key}"}
    resp = requests.delete(endpoint, headers=headers, timeout=30)
    return resp.status_code


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
# 再試行上限ロジック（ローカルモード・クラウドモード共通）
# ---------------------------------------------------------------------------
def _retry_or_give_up(
    post: dict,
    config: dict,
    zernio_api_key: str,
    dry_run: bool,
    retry_count: int,
    ep_number: Optional[int],
    original_post_id: str,
    post_id: str,
) -> Tuple[int, Optional[str]]:
    """
    failed/partial 判定後の共通処理。
    戻り値: (return_code, new_post_id)。
      new_post_id が None でなければ再試行が実施されたことを示す。
      return_code: 1=再試行実施またはスキップ（要通知）、2=上限到達で断念（要通知・pending保持）。
    """
    error_message = extract_error_message(post)
    print(f"✗ 投稿失敗を検出: {error_message}")

    if retry_count >= MAX_RETRY:
        _give_up(
            dry_run, ep_number, original_post_id, post_id, retry_count,
            reason=(error_message or "")[:80],
        )
        return 2, None

    if os.environ.get("VERIFY_DISABLE_RETRY") == "1":
        print("△ VERIFY_DISABLE_RETRY=1: 再試行をスキップ（pending 保持・要手動対応）")
        return 1, None

    if dry_run:
        print("[dry-run] 再スケジュールをスキップ")
        return 1, None

    new_post_id = retry_post(post, config, zernio_api_key)
    new_retry_count = retry_count + 1
    print(f"✓ 再登録完了: 新規投稿ID={new_post_id}")
    print(f"retry {new_retry_count}/{MAX_RETRY} publishAttempts={post.get('publishAttempts')}")
    return 1, new_post_id


# ---------------------------------------------------------------------------
# ステータス別ハンドラ（ローカルモード・従来挙動）
# ---------------------------------------------------------------------------
def handle_failed(post: dict, config: dict, zernio_api_key: str, dry_run: bool) -> int:
    notify_macos("ep投稿がfailedです。自動再試行します", "Zernio検死")

    post_id = post.get("_id", "")
    rc, new_post_id = _retry_or_give_up(
        post,
        config,
        zernio_api_key,
        dry_run,
        retry_count=0,
        ep_number=None,
        original_post_id=post_id,
        post_id=post_id,
    )
    if new_post_id is not None:
        return 0
    return 2


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


def write_pending(
    s3_client,
    bucket: str,
    post_id: str,
    scheduled_iso: str,
    ep_number: Optional[int] = None,
    retry_count: int = 0,
    original_post_id: Optional[str] = None,
) -> str:
    """pending ファイルを登録し、S3 キーを返す（再試行後の新 post_id 用）。"""
    key = f"{PENDING_PREFIX}{post_id}.json"
    payload = {
        "post_id": post_id,
        "scheduled_iso": scheduled_iso,
        "created_at": datetime.now(JST).isoformat(),
        "ep_number": ep_number,
        "retry_count": retry_count,
        "original_post_id": original_post_id if original_post_id is not None else post_id,
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
# Chatwork通知（クラウドモード専用。ローカルモードは notify_macos のまま）
# ---------------------------------------------------------------------------
def _notify_event(dry_run: bool, message: str) -> None:
    if dry_run:
        print("[dry-run] 通知スキップ")
        return
    if not notify(message):
        print("⚠ Chatwork通知に失敗しました（run結果には影響しません）", file=sys.stderr)


def _give_up(
    dry_run: bool,
    ep_number: Optional[int],
    original_post_id: str,
    post_id: str,
    retry_count: int,
    reason: str,
) -> None:
    """上限到達（GIVE_UP）の共通ログ出力＋通知（failed/partial・滞留の両方で使用）。"""
    print(
        f"GIVE_UP ep={ep_number} original={original_post_id} "
        f"last={post_id} retries={retry_count}"
    )
    _notify_event(
        dry_run,
        f"🚨 再試行上限到達・要手動対応 ep{ep_number} original={original_post_id} "
        f"last={post_id} 理由={reason}",
    )


def _handle_stale(
    s3_client,
    bucket: str,
    key: str,
    config: dict,
    zernio_api_key: str,
    dry_run: bool,
    post: dict,
    status: str,
    post_id: str,
    retry_count: int,
    ep_number: Optional[int],
    original_post_id: str,
    elapsed_hours: float,
) -> int:
    """
    滞留（scheduled/publishing が STALE_SCHEDULED_HOURS 超過）の処理。
    DELETE /posts/{postId} で旧予約を取消してから再予約する（Zernio公式：
    scheduled/draft は削除可・published は削除不可のため、二重投稿にならない）。
    戻り値: 0=（本関数では発生しない）、1=要通知、2=上限到達で断念（要通知・pending保持）。
    """
    elapsed_h = round(elapsed_hours, 1)

    if retry_count >= MAX_RETRY:
        _give_up(
            dry_run, ep_number, original_post_id, post_id, retry_count,
            reason=f"{status}のまま{elapsed_h}h滞留",
        )
        return 2

    if os.environ.get("VERIFY_DISABLE_RETRY") == "1":
        print("△ VERIFY_DISABLE_RETRY=1: 取消・再予約をスキップ（pending 保持・要手動対応）")
        _notify_event(
            dry_run, f"⚠️ 投稿が{status}のまま{elapsed_h}h滞留 ep{ep_number} post={post_id}"
        )
        return 1

    if dry_run:
        print("[dry-run] 取消・再予約をスキップ")
        _notify_event(
            dry_run, f"⚠️ 投稿が{status}のまま{elapsed_h}h滞留 ep{ep_number} post={post_id}"
        )
        return 1

    try:
        code = delete_post(zernio_api_key, post_id)
    except Exception as e:
        print(f"✗ delete_post 例外: {type(e).__name__}: {e}", file=sys.stderr)
        _notify_event(
            dry_run,
            f"⚠️ 検死run異常 ep{ep_number} post={post_id} status={status} / "
            f"{type(e).__name__}: {str(e)[:80]}",
        )
        return 1

    if code != 200:
        print(f"✗ delete_post 失敗: code={code}（二重投稿回避のため再予約しません）")
        _notify_event(
            dry_run,
            f"⚠️ 投稿が{status}のまま{elapsed_h}h滞留・取消失敗 code={code} "
            f"ep{ep_number} post={post_id}（要手動）",
        )
        return 1

    new_post_id = retry_post(post, config, zernio_api_key)
    new_retry_count = retry_count + 1
    new_key = write_pending(
        s3_client,
        bucket,
        new_post_id,
        get_retry_scheduled_iso(),
        ep_number=ep_number,
        retry_count=new_retry_count,
        original_post_id=original_post_id,
    )
    print(f"✓ 旧予約DELETE→再予約完了: 新規投稿ID={new_post_id}")
    print(f"✓ 再試行分の pending 登録: {new_key}")
    delete_pending(s3_client, bucket, key)
    print(f"✓ 旧 pending 削除: {key}")
    _notify_event(
        dry_run,
        f"⚠️ 投稿が{status}のまま{elapsed_h}h滞留→旧予約を取消し再予約 ep{ep_number} "
        f"retry {new_retry_count}/{MAX_RETRY} 新ID={new_post_id}",
    )
    return 1


# ---------------------------------------------------------------------------
# クラウドモード（--from-s3）
# ---------------------------------------------------------------------------
def verify_one_pending(
    s3_client, bucket: str, key: str, config: dict, zernio_api_key: str, dry_run: bool
) -> int:
    """pending 1 件を検死する。0=正常、1=要通知（run 失敗にする）、2=再試行上限到達（要通知・pending保持）。"""
    pending = read_pending(s3_client, bucket, key)
    post_id = pending["post_id"]
    retry_count = pending.get("retry_count", 0)
    ep_number = pending.get("ep_number")
    original_post_id = pending.get("original_post_id", pending["post_id"])

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

    if status in ("scheduled", "publishing"):
        scheduled_iso = pending.get("scheduled_iso")
        if scheduled_iso:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_iso)
                elapsed = datetime.now(JST) - scheduled_dt
                if elapsed > timedelta(hours=STALE_SCHEDULED_HOURS):
                    print(
                        f"✗ {status} のまま {STALE_SCHEDULED_HOURS} 時間以上滞留"
                        f"（予定時刻: {scheduled_iso}）"
                    )
                    return _handle_stale(
                        s3_client,
                        bucket,
                        key,
                        config,
                        zernio_api_key,
                        dry_run,
                        post=post,
                        status=status,
                        post_id=post_id,
                        retry_count=retry_count,
                        ep_number=ep_number,
                        original_post_id=original_post_id,
                        elapsed_hours=elapsed.total_seconds() / 3600,
                    )
            except ValueError:
                print(f"⚠ scheduled_iso を解釈できません: {scheduled_iso}")
        print("△ まだ公開時刻前または処理中（pending 保持・翌回再チェック）")
        return 0

    if status in ("failed", "partial"):
        rc, new_post_id = _retry_or_give_up(
            post,
            config,
            zernio_api_key,
            dry_run,
            retry_count=retry_count,
            ep_number=ep_number,
            original_post_id=original_post_id,
            post_id=post_id,
        )
        if new_post_id is not None:
            new_retry_count = retry_count + 1
            new_key = write_pending(
                s3_client,
                bucket,
                new_post_id,
                get_retry_scheduled_iso(),
                ep_number=ep_number,
                retry_count=new_retry_count,
                original_post_id=original_post_id,
            )
            print(f"✓ 再試行分の pending 登録: {new_key}")
            delete_pending(s3_client, bucket, key)
            print(f"✓ 旧 pending 削除: {key}")
            error_snippet = (extract_error_message(post) or "")[:80]
            _notify_event(
                dry_run,
                f"⚠️ 投稿failed→自動再試行 ep{ep_number} retry {new_retry_count}/{MAX_RETRY} "
                f"新ID={new_post_id} 理由={error_snippet}",
            )
        # rc == 2（上限到達）の通知は _retry_or_give_up 内の _give_up() で実施済み
        return rc

    print(f"△ 未知のステータス: {status}")
    _notify_event(
        dry_run,
        f"⚠️ 検死run異常 ep{ep_number} post={post_id} status={status} / 未知ステータス",
    )
    return 1


def main_from_s3(dry_run: bool) -> int:
    """
    未捕捉例外（config/S3クライアント準備段階のReadTimeout等）が起きても、
    ここで1回通知してから従来どおり非ゼロで終了する（main_from_s3()全体の保護）。
    """
    try:
        config = load_config()
        zernio_api_key: str = config["zernio_api_key"]
        bucket: str = config["s3_bucket_name"]
        s3_client = build_s3_client(config)
        keys = list_pending(s3_client, bucket)
    except Exception as e:
        print(f"✗ 検死run異常（準備段階の未捕捉例外）: {type(e).__name__}: {e}", file=sys.stderr)
        _notify_event(
            dry_run,
            f"⚠️ 検死run異常 ep? post=? status=- / {type(e).__name__}: {str(e)[:80]}",
        )
        return 1

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
            post_id_guess = (
                key[len(PENDING_PREFIX):-len(".json")]
                if key.startswith(PENDING_PREFIX) and key.endswith(".json")
                else key
            )
            _notify_event(
                dry_run,
                f"⚠️ 検死run異常 ep? post={post_id_guess} status=- / {type(e).__name__}: {str(e)[:80]}",
            )
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
