#!/Users/utano/artemis-condori/.venv/bin/python3
"""
リール動画自動生成・話数管理スクリプト
バージョン：v1.0
作成日：2026年5月8日

使い方:
    python3 run_episode.py [話数] [台本ファイルパス]

例:
    python3 run_episode.py 28 ~/Downloads/コンドリ/コンドリ動画自動生成/episode_28.txt

処理内容:
    1. 台本ファイルを読み込み
    2. pipeline_final.py を起動して動画生成
    3. 完成動画を episode_[話数]_[YYYYMMDD].mp4 にリネーム

前提:
    - pipeline_final.py が同じ scripts/ フォルダに存在すること
    - config.py の OUTPUT_DIR が ~/Downloads/コンドリ/コンドリ動画自動生成 に設定済み
"""

import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path


# ============================================================
# 設定
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_PATH = SCRIPT_DIR / "pipeline_final.py"

# config.py を読み込んで OUTPUT_DIR を取得
sys.path.insert(0, str(SCRIPT_DIR))
import config

OUTPUT_DIR = Path(os.path.expanduser(config.OUTPUT_DIR))
ORIGINAL_OUTPUT = OUTPUT_DIR / config.OUTPUT_FILENAME  # output_final.mp4

# pipeline に渡すロケーション（ログ表示用・実機能なし）
LOCATION_TAG = "監査官"


# ============================================================
# メイン処理
# ============================================================

def usage_and_exit():
    print("使い方: python3 run_episode.py [話数] [台本ファイルパス] [サムネテキスト（省略可）]")
    print("例:    python3 run_episode.py 28 ~/Downloads/コンドリ/コンドリ動画自動生成/episode_28.txt '午後の眠気は、寝不足のせいではありません'")
    sys.exit(1)


def main():
    # 引数チェック（サムネテキストはオプション）
    if len(sys.argv) < 3:
        usage_and_exit()

    try:
        episode_number = int(sys.argv[1])
    except ValueError:
        print(f"エラー: 話数は整数で指定してください（受け取った値: {sys.argv[1]}）")
        usage_and_exit()

    script_path = Path(os.path.expanduser(sys.argv[2]))
    thumbnail_text = sys.argv[3] if len(sys.argv) > 3 else None

    # 台本ファイルの存在確認
    if not script_path.exists():
        print(f"エラー: 台本ファイルが見つかりません: {script_path}")
        sys.exit(1)

    # 台本読み込み
    print(f"[1/4] 台本ファイル読み込み: {script_path}")
    script_text = script_path.read_text(encoding="utf-8").strip()

    if not script_text:
        print(f"エラー: 台本ファイルが空です: {script_path}")
        sys.exit(1)

    char_count = len(script_text)
    print(f"  → 文字数: {char_count}字")

    if "【ナレーション】" in script_text and "【テロップ】" in script_text:
        # B方式：ナレーション部分の文字数をチェック
        _narr_part = script_text.split("【テロップ】")[0].split("【ナレーション】", 1)[1].strip()
        _narr_count = len(_narr_part)
        print(f"  → B方式検出: ナレーション {_narr_count}字")
        if _narr_count < 40 or _narr_count > 80:
            print(f"  ⚠ 警告: ナレーションが想定範囲（55〜65字）から大きく外れています")
    else:
        if char_count < 200 or char_count > 450:
            print(f"  ⚠ 警告: 文字数が想定範囲（320〜360字）から大きく外れています")
            # 警告のみ・処理は継続

    # 台本テキストを episode_[話数].txt として保存
    episode_txt_path = OUTPUT_DIR / f"episode_{episode_number}.txt"
    print(f"\n[2/4] 台本テキスト保存: {episode_txt_path}")
    episode_txt_path.write_text(script_text, encoding="utf-8")
    print(f"  ✓ 保存完了")

    # pipeline_final.py 起動
    print(f"\n[3/4] pipeline_final.py 起動中...")
    print(f"  話数: 第{episode_number}話")
    print(f"  ロケーションタグ: {LOCATION_TAG}")
    if thumbnail_text:
        print(f"  サムネテキスト: {thumbnail_text}")
    print()

    cmd = [
        "python3",
        str(PIPELINE_PATH),
        script_text,
        LOCATION_TAG,
        thumbnail_text if thumbnail_text else "",
        str(episode_number),
    ]

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\nエラー: pipeline_final.py の実行に失敗しました（exit code: {result.returncode}）")
        sys.exit(result.returncode)

    # 完成動画のリネーム
    print(f"\n[4/4] 完成動画をリネーム中...")

    if not ORIGINAL_OUTPUT.exists():
        print(f"エラー: 完成動画が見つかりません: {ORIGINAL_OUTPUT}")
        print(f"  pipeline_final.py の出力先設定を確認してください")
        sys.exit(1)

    today_str = datetime.now().strftime("%Y%m%d")
    new_filename = f"episode_{episode_number}_{today_str}.mp4"
    new_path = OUTPUT_DIR / new_filename

    # 既存ファイルがある場合はバックアップ
    if new_path.exists():
        backup_path = new_path.with_suffix(f".bak_{datetime.now().strftime('%H%M%S')}.mp4")
        new_path.rename(backup_path)
        print(f"  ⚠ 既存ファイルをバックアップ: {backup_path.name}")

    ORIGINAL_OUTPUT.rename(new_path)
    print(f"  ✓ リネーム完了: {new_path.name}")

    # サムネイルのリネーム
    if thumbnail_text:
        original_thumbnail = OUTPUT_DIR / "thumbnail.png"
        if original_thumbnail.exists():
            new_thumbnail_name = f"thumbnail_{episode_number}.png"
            new_thumbnail_path = OUTPUT_DIR / new_thumbnail_name
            if new_thumbnail_path.exists():
                new_thumbnail_path.unlink()
            original_thumbnail.rename(new_thumbnail_path)
            print(f"  ✓ サムネイルリネーム完了: {new_thumbnail_name}")
        else:
            print(f"  ⚠ サムネイルファイルが見つかりません: {original_thumbnail}")

    print(f"\n=== 完了 ===")
    print(f"完成動画: {new_path}")
    if thumbnail_text:
        print(f"サムネイル: {OUTPUT_DIR / f'thumbnail_{episode_number}.png'}")


if __name__ == "__main__":
    main()
