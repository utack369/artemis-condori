#!/usr/bin/env python3
"""監視②：バックアップログ検査（夜間照合 例外検知型移行）。

~/Library/Logs/artemis-backup.log の最新の完了ブロックを解析し、
異常時のみ Chatwork に通知する（notify_chatwork.notify を使用）。

通知条件（いずれか）:
  1. exit_code != 0
  2. ブロック内に [retry] 行あり
  3. matching 件数が前回より減少
  4. ブロック内に rclone の再試行/エラー行（"Attempt N/M failed" / " ERROR :"）あり

冪等性: 処理済みENDタイムスタンプを state に記録。WatchPaths で複数回起動しても
同一ブロックは再通知しない。初回はベースライン記録のみ（減少判定なし）。

--backstop: 深夜起動用。直近6時間以内に完了ブロックが無ければ「未完了/未実行」を通知。

テスト用に環境変数で入出力を差し替え可能:
  ARTEMIS_BACKUP_LOG   … ログのパス
  ARTEMIS_BACKUP_STATE … stateのパス
"""
from __future__ import annotations

import os
import re
import sys
import json
import datetime
from pathlib import Path

from notify_chatwork import notify

LOG_PATH = Path(os.environ.get(
    "ARTEMIS_BACKUP_LOG", str(Path.home() / "Library/Logs/artemis-backup.log")))
STATE_PATH = Path(os.environ.get(
    "ARTEMIS_BACKUP_STATE", str(Path.home() / "artemis-media/backup_state.json")))

START_RE = re.compile(r"^=== START (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ===")
END_RE = re.compile(r"^=== END (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) exit_code=(\d+) ===")
MATCHING_RE = re.compile(r"'[^']*':\s*(\d+)\s+matching files")
RETRY_RE = re.compile(r"\[retry\]")
ATTEMPT_FAIL_RE = re.compile(r"Attempt \d+/\d+ failed")
ERROR_RE = re.compile(r"\bERROR\b\s*:")


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _parse_blocks(lines):
    blocks = []
    cur = None
    for ln in lines:
        ms = START_RE.match(ln)
        if ms:
            cur = {"start": ms.group(1), "lines": [], "end": None, "exit": None}
            continue
        if cur is not None:
            me = END_RE.match(ln)
            if me:
                cur["end"] = me.group(1)
                cur["exit"] = int(me.group(2))
                blocks.append(cur)
                cur = None
            else:
                cur["lines"].append(ln)
    return blocks


def _latest_start(lines):
    latest = None
    for ln in lines:
        ms = START_RE.match(ln)
        if ms:
            latest = ms.group(1)
    return latest


def _matching_count(block):
    counts = [int(m.group(1)) for ln in block["lines"]
              for m in [MATCHING_RE.search(ln)] if m]
    return counts[-1] if counts else None


def _to_dt(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def run_watch():
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = _parse_blocks(lines)
    if not blocks:
        return
    block = blocks[-1]
    state = _load_state()
    if state.get("last_processed_end") == block["end"]:
        return
    matching = _matching_count(block)
    reasons = []
    if block["exit"] != 0:
        reasons.append(f"exit_code={block['exit']}（非0）")
    retry_lines = [ln for ln in block["lines"] if RETRY_RE.search(ln)]
    if retry_lines:
        reasons.append(f"[retry]行 {len(retry_lines)}件")
    err_lines = [ln for ln in block["lines"]
                 if ATTEMPT_FAIL_RE.search(ln) or ERROR_RE.search(ln)]
    if err_lines:
        reasons.append(f"再試行/エラー行 {len(err_lines)}件")
    prev = state.get("last_matching")
    if prev is not None and matching is not None and matching < prev:
        reasons.append(f"matching減少 {prev}→{matching}")

    if reasons:
        sample = "\n".join((retry_lines + err_lines)[:5])
        msg = (
            "[info][title]⚠️ バックアップ異常検知（監視②）[/title]"
            f"対象: {block['start']} 〜 {block['end']}\n"
            f"検知: {' / '.join(reasons)}\n"
            f"exit_code={block['exit']} / matching={matching}（前回={prev}）"
            + (f"\n該当行(先頭5):\n{sample}" if sample else "")
            + "[/info]"
        )
        notify(msg)

    state["last_processed_end"] = block["end"]
    if matching is not None:
        state["last_matching"] = matching
    _save_state(state)


def run_backstop():
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = _parse_blocks(lines)
    now = datetime.datetime.now()
    recent = None
    for b in blocks:
        try:
            if now - _to_dt(b["start"]) <= datetime.timedelta(hours=6):
                recent = b
        except Exception:
            pass
    if recent is None:
        latest_start = _latest_start(lines)
        msg = (
            "[info][title]⚠️ バックアップ未完了/未実行（監視②・保険）[/title]"
            "深夜時点で直近6時間以内に完了ブロックがありません。\n"
            f"最新START: {latest_start or '（なし）'}\n"
            "バックアップがハングまたは未発火の可能性があります。[/info]"
        )
        notify(msg)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--backstop":
        run_backstop()
    else:
        run_watch()
