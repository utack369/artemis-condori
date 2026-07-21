#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Instagram カルーセル予約投稿スクリプト（Zernio API + S3 署名付き URL 方式）

使用方法:
  python scripts/post_carousel.py <ep_number> [--check-only]

例:
  python scripts/post_carousel.py 34
  python scripts/post_carousel.py 34 --check-only  # 事前チェックのみ・実投稿/予約なし

仕組み:
  output/instagram/ep<N>/slides/slide_<N>_*.png（7〜8枚）をS3にアップロードし、
  Zernio API の mediaItems に画像を複数並べてカルーセルとして予約投稿する。
  カルーセルは contentType 指定不要（mediaItemsが複数画像なら自動でカルーセルになる）。
  共通処理（設定読込・S3・予約時刻・検死ジョブ）は post_reel.py から import する。

前提:
  post_reel.py と同一（config.json の zernio_api_key / zernio_account_id / S3設定）
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import requests

from post_reel import (
    JST,
    OUTPUT_BASE,
    PRESIGNED_URL_EXPIRY,
    ZERNIO_API_BASE,
    build_s3_client,
    check_media_url,
    generate_presigned_url,
    get_scheduled_iso,
    load_config,
    mask_signed_urls,
    schedule_verify_job,
)

MIN_SLIDES = 7
MAX_SLIDES = 8
S3_PREFIX = "carousels"


def get_carousel_files(ep_num: int) -> Tuple[List[Path], str]:
    """output/instagram/ep<N>/ からスライド画像群とキャプションを取得する。"""
    ep_dir = OUTPUT_BASE / f"ep{ep_num}"
    if not ep_dir.exists():
        raise FileNotFoundError(f"エピソードフォルダが見つかりません: {ep_dir}")

    slides_dir = ep_dir / "slides"
    slide_paths = sorted(slides_dir.glob(f"slide_{ep_num}_*.png"))
    if not slide_paths:
        raise FileNotFoundError(f"スライド画像が見つかりません: {slides_dir}")
    if not (MIN_SLIDES <= len(slide_paths) <= MAX_SLIDES):
        raise ValueError(
            f"スライド枚数が{MIN_SLIDES}〜{MAX_SLIDES}枚ではありません（{len(slide_paths)}枚）"
        )

    for caption_name in [f"caption_{ep_num}.txt", "caption.md"]:
        caption_file = ep_dir / caption_name
        if caption_file.exists():
            return slide_paths, caption_file.read_text(encoding="utf-8").strip()

    raise FileNotFoundError(f"キャプションファイルが見つかりません: {ep_dir}")


def upload_slide_to_s3(s3_client, bucket: str, slide_path: Path, ep_num: int) -> str:
    """スライド画像を S3 にアップロードし、S3 キーを返す。"""
    s3_key = f"{S3_PREFIX}/{ep_num}/{slide_path.name}"
    size_mb = slide_path.stat().st_size / 1024 / 1024
    print(f"  {slide_path.name} ({size_mb:.1f} MB) → s3://{bucket}/{s3_key}")
    s3_client.upload_file(
        str(slide_path),
        bucket,
        s3_key,
        ExtraArgs={"ContentType": "image/png"},
    )
    return s3_key


def post_carousel_to_zernio(
    zernio_api_key: str,
    account_id: str,
    image_urls: List[str],
    caption: str,
    scheduled_iso: str,
) -> str:
    """Zernio API にカルーセル予約投稿リクエストを送信し、post._id を返す。"""
    endpoint = f"{ZERNIO_API_BASE}/posts"
    headers = {
        "Authorization": f"Bearer {zernio_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "platforms": [
            {
                "platform": "instagram",
                "accountId": account_id,
                # カルーセルは contentType 指定不要（feedがデフォルト）。
                # CTAなし方針のため firstComment も使用しない。
            }
        ],
        "content": caption,
        "mediaItems": [{"url": url, "type": "image"} for url in image_urls],
        "scheduledFor": scheduled_iso,
    }

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    try:
        print(f"[DEBUG] Zernio API Response ({resp.status_code}): {mask_signed_urls(resp.text)[:300]}")
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


def main() -> None:
    argv = sys.argv[1:]
    check_only = "--check-only" in argv
    positional = [a for a in argv if a != "--check-only"]

    if not positional:
        print(
            "使用方法: python scripts/post_carousel.py <ep_number> [--check-only]",
            file=sys.stderr,
        )
        sys.exit(1)

    ep_num = int(positional[0])

    slide_paths, caption = get_carousel_files(ep_num)
    scheduled_iso = get_scheduled_iso()
    scheduled_jst = datetime.fromisoformat(scheduled_iso).strftime("%Y-%m-%d %H:%M JST")

    print(f"\n{'=' * 52}")
    print(f"  ep{ep_num} カルーセル予約投稿（Zernio API）")
    print(f"{'=' * 52}")
    print(f"スライド: {len(slide_paths)}枚")
    for p in slide_paths:
        print(f"          {p.name}")
    print(f"公開予定: {scheduled_jst}")
    print(f"キャプ  : {caption[:60]}{'...' if len(caption) > 60 else ''}")
    print()

    if check_only:
        print("--check-only: ファイル・枚数チェックを通過しました。実投稿・予約には進まず終了します。")
        sys.exit(0)

    config = load_config()
    zernio_api_key: str = config["zernio_api_key"]
    bucket: str = config["s3_bucket_name"]
    s3_client = build_s3_client(config)

    # Step 1: S3 にスライド画像をアップロード
    print("Step 1: S3 へスライド画像アップロード")
    s3_keys = [
        upload_slide_to_s3(s3_client, bucket, p, ep_num) for p in slide_paths
    ]
    print("  アップロード完了")

    # Step 2: 署名付き URL を生成
    print("\nStep 2: 署名付き URL 生成")
    image_urls = [generate_presigned_url(s3_client, bucket, k) for k in s3_keys]
    print(f"  {len(image_urls)}件生成（有効期限 {PRESIGNED_URL_EXPIRY // 86400} 日）")

    # Step 2.5: メディア URL 到達性チェック（全枚数）
    print("\nStep 2.5: メディア URL 到達性チェック")
    for i, url in enumerate(image_urls, start=1):
        if not check_media_url(url, f"スライド{i}"):
            sys.exit(1)

    # Step 3: Zernio API に予約投稿
    print("\nStep 3: Zernio API 予約投稿（カルーセル）")
    post_id = post_carousel_to_zernio(
        zernio_api_key,
        config["zernio_account_id"],
        image_urls,
        caption,
        scheduled_iso,
    )

    # Step 4: 検死ジョブ登録
    print("\nStep 4: 検死ジョブ登録")
    schedule_verify_job(post_id, datetime.fromisoformat(scheduled_iso))

    print(f"\n{'=' * 52}")
    print(f"  予約投稿完了!")
    print(f"  投稿ID  : {post_id}")
    print(f"  公開予定: {scheduled_jst}")
    print(f"{'=' * 52}\n")


if __name__ == "__main__":
    main()
