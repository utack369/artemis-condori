#!/usr/bin/env python3
"""Chatwork通知共通モジュール（夜間照合 例外検知型移行）v2。

config.json から chatwork_api_token / chatwork_room_id / chatwork_to を読み、
Chatwork API v2 にメッセージを投稿する。chatwork_to が設定されていれば
本文先頭にメンション（[toall] または [To:ID]）を付与する。
失敗時はローカルログに記録する。
"""
from __future__ import annotations

import sys
import json
import datetime
from pathlib import Path

import requests

CONFIG_PATH = Path.home() / "artemis-media/自動取得システム/config.json"
LOG_PATH = Path.home() / "artemis-media/logs/notify_chatwork.log"
API_BASE = "https://api.chatwork.com/v2"
TIMEOUT = 20


def _log(line: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")
    except Exception:
        pass


def _load_creds() -> tuple[str, str, str]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return (
        cfg["chatwork_api_token"],
        str(cfg["chatwork_room_id"]),
        str(cfg.get("chatwork_to", "")).strip(),
    )


def _mention_prefix(to_value: str) -> str:
    if not to_value:
        return ""
    if to_value.lower() == "toall":
        return "[toall]\n"
    return f"[To:{to_value}]\n"


def notify(message: str) -> bool:
    """Chatworkにmessageを投稿。成功=True / 失敗=False。失敗時はローカルログに記録。"""
    try:
        token, room_id, to_value = _load_creds()
    except Exception as e:
        _log(f"[config-error] {type(e).__name__}: {e}")
        return False
    body = _mention_prefix(to_value) + message
    url = f"{API_BASE}/rooms/{room_id}/messages"
    headers = {"X-ChatWorkToken": token}
    data = {"body": body}
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=TIMEOUT)
    except Exception as e:
        _log(f"[request-error] {type(e).__name__}: {e}")
        return False
    if resp.status_code == 200:
        _log(f"[ok] posted ({len(body)} chars)")
        return True
    _log(f"[http-error] status={resp.status_code} body={resp.text[:300]}")
    return False


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "テスト通知（notify_chatwork.py 疎通確認）"
    ok = notify(msg)
    print("notify:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
