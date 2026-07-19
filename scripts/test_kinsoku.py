#!/usr/bin/env python3
"""
scripts/generate_carousel.py の wrap_line 禁則処理を検証する機械テスト。

使用方法:
  python3 scripts/test_kinsoku.py

検証内容:
  本番と同じフォントロード（find_font_path）を使い、狭いmax_widthで折り返しを
  強制した上で、以下を全行についてassertする。
    - 行頭がKINSOKU_HEADでない（1文字行の縮退ケースは除く）
    - 行末がKINSOKU_TAILでない
    - SEPARATION_CHARS（…―‥）の連続が行境界で分断されていない
    - ぶら下げ（行末がBURASAGE）以外で行幅超過なし
    - 折り返し前後で文字の欠落・重複がない（全行を連結すると元テキストに一致）
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from generate_carousel import (  # noqa: E402
    BURASAGE,
    KINSOKU_HEAD,
    KINSOKU_TAIL,
    SEPARATION_CHARS,
    find_font_path,
    wrap_line,
)

TEST_CASES = {
    "a_continuous_kinsoku": "彼は「もう大丈夫です。」と静かに言った。それから外を見た。",
    "b_open_bracket": (
        "彼は「これは大事な話だ」と言い、また「もう一つある」と続けた。"
        "最後に「これで終わりだ」と静かに言った。"
    ),
    "c_separation_chars": (
        "彼はそこまで話すと――そのまま黙り込んでしまった……。"
        "それからしばらくして、また話し始めた――今度はゆっくりと……。"
    ),
    "d_small_kana": (
        "ちょっと待ってください、あとでゆっくり話しましょう。"
        "急いでいるので、ちょっとだけ時間をください。"
    ),
}


def setup_draw_and_font():
    font_path = find_font_path()
    if font_path is None:
        print("✗ 日本語フォントが見つかりません（ヒラギノ／Noto CJK）")
        sys.exit(1)
    img = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 60)
    # 狭いmax_width：全角6文字分程度に固定し、折り返しを強制する
    max_width = draw.textbbox((0, 0), "あいうえおか", font=font)[2]
    return draw, font, font_path, max_width


def assert_no_split_separation(name, lines):
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if a and b and a[-1] in SEPARATION_CHARS and b[0] == a[-1]:
            raise AssertionError(
                f"[{name}] 分離禁則違反：行{i}末尾『{a[-1]}』と行{i+1}先頭が同一のSEPARATION_CHARSで分断: "
                f"{a!r} / {b!r}"
            )


def assert_head_tail_and_width(name, draw, font, max_width, lines):
    for i, line in enumerate(lines):
        if not line:
            continue
        # 行頭禁則（1文字行の縮退ケースは除く）
        if len(line) > 1 and line[0] in KINSOKU_HEAD:
            raise AssertionError(f"[{name}] 行頭禁則違反：行{i}『{line}』の先頭『{line[0]}』がKINSOKU_HEAD")
        # 行末禁則
        if line[-1] in KINSOKU_TAIL:
            raise AssertionError(f"[{name}] 行末禁則違反：行{i}『{line}』の末尾『{line[-1]}』がKINSOKU_TAIL")
        # 行幅超過チェック（ぶら下げ以外は超過禁止）
        w = draw.textbbox((0, 0), line, font=font)[2]
        if w > max_width and line[-1] not in BURASAGE:
            raise AssertionError(
                f"[{name}] 行幅超過違反：行{i}『{line}』の幅{w}がmax_width{max_width}を超過（ぶら下げ以外）"
            )


def assert_no_char_loss(name, original, lines):
    joined = "".join(lines)
    if joined != original:
        raise AssertionError(
            f"[{name}] 文字の欠落・重複あり：\n  元      : {original!r}\n  折り返し後: {joined!r}"
        )


def main():
    draw, font, font_path, max_width = setup_draw_and_font()
    print(f"[TEST] フォント: {font_path}")
    print(f"[TEST] max_width: {max_width}px（狭い幅で折り返しを強制）\n")

    for name, text in TEST_CASES.items():
        lines = wrap_line(draw, text, font, max_width)
        print(f"--- {name} ---")
        print(f"  元テキスト: {text}")
        for i, line in enumerate(lines):
            print(f"  行{i}: {line}")

        assert_head_tail_and_width(name, draw, font, max_width, lines)
        assert_no_split_separation(name, lines)
        assert_no_char_loss(name, text, lines)
        print(f"  ✓ {name} 合格（{len(lines)}行）\n")

    print("[TEST] 全ケース合格")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ 検証失敗: {e}")
        sys.exit(1)
