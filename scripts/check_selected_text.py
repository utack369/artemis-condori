#!/Users/utano/artemis-condori/.venv/bin/python3
"""
thumbnail_guideline.selected_text 機械検証スクリプト

使用方法:
  python scripts/check_selected_text.py <input/instagram/ep<N>.json>

検証内容:
  1. selected_text が配列で2〜4要素
  2. 各要素が最大7文字
  3. 各要素が約物・記号を含まない
     （許容: ひらがな・カタカナ・漢字・英数字・長音「ー」のみ）
"""

import json
import re
import sys
from pathlib import Path

MIN_LINES = 2
MAX_LINES = 4
MAX_CHARS_PER_LINE = 7

# 許容文字: ひらがな・カタカナ（中点・゠ 等の記号を除く）・長音「ー」・漢字・英数字
ALLOWED_CHAR_PATTERN = re.compile(
    r"[ぁ-ゖァ-ヺーa-zA-Z0-9一-鿿]"
)


def validate(selected_text) -> list:
    """selected_text の違反理由を列挙する（空リストなら合格）。"""
    violations = []

    if not isinstance(selected_text, list):
        return [
            f"selected_text は配列である必要があります"
            f"（実際の型: {type(selected_text).__name__}）"
        ]

    if not (MIN_LINES <= len(selected_text) <= MAX_LINES):
        violations.append(
            f"selected_text の要素数が{MIN_LINES}〜{MAX_LINES}の範囲外です"
            f"（実際: {len(selected_text)}要素）"
        )

    for i, line in enumerate(selected_text, start=1):
        if not isinstance(line, str):
            violations.append(
                f"{i}行目: 文字列ではありません（実際の型: {type(line).__name__}）"
            )
            continue

        if len(line) > MAX_CHARS_PER_LINE:
            violations.append(
                f"{i}行目「{line}」: {len(line)}文字（最大{MAX_CHARS_PER_LINE}文字を超過）"
            )

        bad_chars = sorted({c for c in line if not ALLOWED_CHAR_PATTERN.fullmatch(c)})
        if bad_chars:
            violations.append(
                f"{i}行目「{line}」: 約物・記号を含みます（{''.join(bad_chars)}）"
            )

    return violations


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "使用方法: python scripts/check_selected_text.py <input/instagram/ep<N>.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    json_path = Path(sys.argv[1])

    if not json_path.exists():
        print(f"✗ ファイルが見つかりません: {json_path}")
        sys.exit(1)

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"✗ JSON構文エラー: {json_path}: {e}")
        sys.exit(1)

    thumbnail_guideline = data.get("thumbnail_guideline")
    if not isinstance(thumbnail_guideline, dict):
        print(f"✗ キー欠落: thumbnail_guideline が存在しません: {json_path}")
        sys.exit(1)

    if "selected_text" not in thumbnail_guideline:
        print(f"✗ キー欠落: thumbnail_guideline.selected_text が存在しません: {json_path}")
        sys.exit(1)

    violations = validate(thumbnail_guideline["selected_text"])

    if violations:
        print(f"✗ selected_text 検証NG: {json_path}")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)

    print("OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
