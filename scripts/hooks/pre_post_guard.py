#!/usr/bin/env python3
"""PreToolUse hook: scripts/post_reel.py・scripts/post_carousel.py 実行直前の機械検証。
検証1=成果物実在／検証2=design_master整合／検証3=HEAD一致・クリーン。
1つでもNGならexit 2でツール実行をブロックする。exit 1は使わない（公式仕様：exit 2=ブロック）。
実投稿・commit/pushはこのHook自体は一切行わない。標準ライブラリのみで実装。
"""
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

PREFIX = "[post-guard]"
TARGET_SCRIPT_RE = re.compile(r"scripts/post_(reel|carousel)\.py")
EP_ARG_RE = re.compile(r"scripts/post_(reel|carousel)\.py\s+(\d+)")

MIN_SLIDES = 7
MAX_SLIDES = 8


def log(msg: str) -> None:
    print(f"{PREFIX} {msg}", file=sys.stderr)


def resolve_project_root(payload: dict) -> Path:
    """$CLAUDE_PROJECT_DIRを優先し、無ければpayload.cwd、それも無ければカレントを使う。"""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root).resolve()
    cwd = payload.get("cwd")
    if cwd:
        return Path(cwd).resolve()
    return Path(".").resolve()


def check_artifacts(root: Path, media: str, ep: int):
    """検証1：媒体種別ごとの必須入力ファイルが実在するか。
    参照元: scripts/post_reel.py get_episode_files() / scripts/post_carousel.py get_carousel_files()
    """
    ep_dir = root / "output" / "instagram" / f"ep{ep}"
    if not ep_dir.is_dir():
        return False, f"エピソードフォルダが存在しません: {ep_dir}"

    if media == "reel":
        mp4_files = sorted(ep_dir.glob("*.mp4"))
        if not mp4_files:
            return False, f"MP4ファイルが存在しません: {ep_dir}"
    else:
        slides_dir = ep_dir / "slides"
        slide_paths = sorted(slides_dir.glob(f"slide_{ep}_*.png"))
        if not (MIN_SLIDES <= len(slide_paths) <= MAX_SLIDES):
            return False, (
                f"スライド画像が{MIN_SLIDES}〜{MAX_SLIDES}枚ではありません"
                f"（実測{len(slide_paths)}枚）: {slides_dir}"
            )

    caption_ok = any(
        (ep_dir / name).exists() for name in (f"caption_{ep}.txt", "caption.md")
    )
    if not caption_ok:
        return False, f"キャプションファイルが存在しません: {ep_dir}"

    return True, "成果物実在OK"


def get_design_entry(root: Path, ep: int):
    """design_master.mdのFile.{ep:02d}行から ('type', 'Type_N') か ('carousel', 'カテゴリ') を返す。未定義行はNone。
    流用元: .claude/hooks/check_type.py の get_design_entry()（同一パース規則）。
    """
    master_path = root / "refs" / "design_master.md"
    if not master_path.is_file():
        return None
    key = f"File.{ep:02d}"
    for line in master_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + " "):
            m = re.search(r"(Type_\d+)", line)
            if m:
                return ("type", m.group(1))
            m2 = re.search(r"Carousel:(comparison|checklist|warning)", line)
            if m2:
                return ("carousel", m2.group(1))
            return None
    return None


def check_design_master(root: Path, media: str, ep: int):
    """検証2：File.{ep}行の媒体種別と呼び出しスクリプト種別が一致するか。"""
    entry = get_design_entry(root, ep)
    if entry is None:
        return False, f"design_master.md に File.{ep:02d} の定義がありません"
    kind, value = entry
    expected_media = "reel" if kind == "type" else "carousel"
    if expected_media != media:
        return False, (
            f"媒体種別不一致：design_master=File.{ep:02d} {value}（{expected_media}）、"
            f"呼び出しスクリプト=post_{media}.py"
        )
    return True, f"design_master整合OK（File.{ep:02d} {value}）"


def check_head(root: Path):
    """検証3：ローカルHEADとorigin/mainのref一致・作業ツリークリーン（fetchなし・ネットワーク非依存）。"""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    origin = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=root, capture_output=True, text=True
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    if head.returncode != 0 or origin.returncode != 0 or status.returncode != 0:
        return False, (
            "git コマンドの実行に失敗しました: "
            f"HEAD(rc={head.returncode}) origin/main(rc={origin.returncode}) status(rc={status.returncode})"
        )

    head_sha = head.stdout.strip()
    origin_sha = origin.stdout.strip()
    dirty = status.stdout.strip()

    if head_sha != origin_sha:
        return False, f"HEAD不一致：HEAD={head_sha} / origin/main={origin_sha}"
    if dirty:
        return False, f"作業ツリーがクリーンではありません:\n{dirty}"
    return True, f"HEAD一致・クリーンOK（{head_sha}）"


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not TARGET_SCRIPT_RE.search(command):
        return 0

    m = EP_ARG_RE.search(command)
    if not m:
        log("ep番号を抽出できません（抽出不能はfail-closed・exit 2）")
        log(f"command: {command}")
        return 2

    media = m.group(1)
    ep = int(m.group(2))

    root = resolve_project_root(payload)

    checks = [
        ("検証1（成果物実在）", check_artifacts(root, media, ep)),
        ("検証2（design_master整合）", check_design_master(root, media, ep)),
        ("検証3（HEAD一致・クリーン）", check_head(root)),
    ]

    all_ok = True
    for label, (ok, detail) in checks:
        status = "OK" if ok else "NG"
        log(f"{label}: {status} - {detail}")
        if not ok:
            all_ok = False

    if not all_ok:
        log(f"ブロック：post_{media}.py ep{ep} の実行を許可しません（exit 2）")
        return 2

    log(f"全検証OK：post_{media}.py ep{ep} の実行を許可します（exit 0）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(f"{PREFIX} 予期しない例外が発生しました（fail-closed・exit 2）", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)
