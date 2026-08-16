#!/usr/bin/env python3
"""監視③：S3 verification/pending 残留照会（夜間照合 例外検知型移行）。

post_reel の load_config / build_s3_client を流用して
S3 の verification/pending/ プレフィックスを照会し、
残留（pending != 0）があれば Chatwork に通知する。翌朝の launchd 起動を想定。

照会自体が失敗した場合も、監視が盲目化するのを避けるため通知する。
"""
from __future__ import annotations

import sys

from post_reel import load_config, build_s3_client
from notify_chatwork import notify

PREFIX = "verification/pending/"


def run() -> int:
    try:
        cfg = load_config()
        s3 = build_s3_client(cfg)
        resp = s3.list_objects_v2(Bucket=cfg["s3_bucket_name"], Prefix=PREFIX)
        items = resp.get("Contents", [])
        keys = [o["Key"] for o in items if not o["Key"].endswith("/")]
    except Exception as e:
        notify(
            "[info][title]⚠️ 監視③実行エラー（S3 pending照会）[/title]"
            f"pending照会に失敗しました: {type(e).__name__}: {e}\n"
            "S3認証・ネットワーク等を確認してください。[/info]"
        )
        return 2

    n = len(keys)
    print(f"pending件数: {n}")
    for k in keys:
        print(" -", k)

    if n > 0:
        listed = "\n".join(f" - {k}" for k in keys[:20])
        msg = (
            "[info][title]⚠️ S3 pending残留（監視③）[/title]"
            f"翌朝時点で pending が {n} 件残っています。\n"
            f"{listed}\n"
            "夜間runでの公開/削除が完了していない可能性があります。[/info]"
        )
        notify(msg)
    return 0


if __name__ == "__main__":
    sys.exit(run())
