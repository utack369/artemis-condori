#!/usr/bin/env python3
"""
カルーセルスライド画像生成スクリプト

使用方法:
  python3 scripts/generate_carousel.py <ep番号> <carousel_slides.mdパス> <出力ディレクトリ>

処理内容:
  carousel_slides.md（【スライドN｜role】ブロック構造）を解析し、
  スライドごとに 1080x1350 のPNG画像（slide_[ep]_[n].png）を生成する。
  文字はPillowで描画する（生成AIに文字を描かせない＝文字品質と機械検証性の担保）。
  背景は差し替え可能な関数に分離（将来のGemini API背景生成に対応）。
"""

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ============================================================
# 定数（ブランドトーン：白・グレー系・余白多め）
# ============================================================
CANVAS_W = 1080
CANVAS_H = 1350

# 配色は3色以内（保存率設計の定石）：ダーク・オフホワイト・アクセント
DARK_BG = (38, 38, 40)            # 表紙・締めの背景（フィードで反転して止める）
LIGHT_BG = (244, 244, 242)        # 本文の背景
TEXT_ON_DARK = (255, 255, 255)
TEXT_ON_LIGHT = (43, 43, 43)
SUB_ON_DARK = (170, 170, 170)
SUB_ON_LIGHT = (140, 140, 140)
NUM_COLOR = (210, 210, 206)       # 本文の大きな薄番号
ACCENT_COLOR = (214, 177, 66)     # 黄土（誠実トーンの1差し色）

MARGIN = 100                      # 左右余白
COVER_FONT_MAX = 92
BODY_FONT_MAX = 72
FONT_MIN = 36
LINE_SPACING_RATIO = 0.45         # 行間（フォントサイズ比）

# 行頭に置かない文字（禁則処理）
KINSOKU_HEAD = "、。，．・：；？！」』）〉》】ゝゞ々ーぁぃぅぇぉっゃゅょァィゥェォッャュョ"
# ぶら下げを許容する文字（行頭禁則のうちこれだけは行幅超過を許して前行末に含める）
BURASAGE = "、。，．"
# 行末に置かない文字（開き括弧類。次行頭へ追い出す）
KINSOKU_TAIL = "「『（〈《【"
# 同一文字の連続を1トークンとして扱い、行またぎで分断しない記号（分離禁則）
SEPARATION_CHARS = "…―‥"

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",   # 本番Mac（太）
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",   # 本番Mac（細）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",     # 検証環境
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

NUMBERING_PATTERN = re.compile(r"安全靴と戦う12年の記録：File\.\d+")
# 正規形式は【スライドN｜role】。生成揺れ（【N｜role】）も受容する（Postel の法則）
BLOCK_PATTERN = re.compile(r"【(?:スライド)?(\d+)｜(\w+)】")


def find_font_path():
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def parse_slides(md_text):
    """carousel_slides.md を [{number, role, lines}] に解析する。"""
    matches = list(BLOCK_PATTERN.finditer(md_text))
    if not matches:
        raise ValueError("【スライドN｜role】ブロックが見つかりません")
    slides = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        lines = [l.strip() for l in md_text[start:end].strip().splitlines() if l.strip()]
        slides.append({
            "number": int(m.group(1)),
            "role": m.group(2),
            "lines": lines,
        })
    return slides


def make_background(role, width, height):
    """背景画像を返す。将来のGemini API背景生成はこの関数の差し替えで対応する。
    表紙・締め＝ダーク（フィードで反転して止める）、本文＝オフホワイト（読みやすさ）。"""
    is_dark = role in ("cover", "summary", "personal_comment")
    return Image.new("RGB", (width, height), DARK_BG if is_dark else LIGHT_BG)


def _is_katakana(ch):
    """全角カタカナ（ァ〜ヴ）と長音「ー」を対象とする。中黒「・」は結合対象外。"""
    return ("ァ" <= ch <= "ヺ") or ch == "ー"


def _tokenize_for_wrap(text):
    """通常は1文字=1トークン。カタカナ連続（長音含む）とSEPARATION_CHARSの同一文字連続は1トークンにまとめる。"""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if _is_katakana(ch):
            j = i + 1
            while j < n and _is_katakana(text[j]):
                j += 1
            tokens.append(text[i:j])
            i = j
        elif ch in SEPARATION_CHARS:
            j = i + 1
            while j < n and text[j] == ch:
                j += 1
            tokens.append(text[i:j])
            i = j
        else:
            tokens.append(ch)
            i += 1
    return tokens


def _build_wrap_units(draw, text, font, max_width):
    """分離禁則トークンのうち、単体で行幅を超えるものだけ1文字単位に分割し直す。"""
    units = []
    for tok in _tokenize_for_wrap(text):
        if len(tok) > 1:
            w = draw.textbbox((0, 0), tok, font=font)[2]
            if w > max_width:
                units.extend(list(tok))
                continue
        units.append(tok)
    return units


def _trim_kinsoku_tail(line):
    """行末がKINSOKU_TAIL（開き括弧類）なら、連続する分を次行送りにする（最低1文字は残す）。"""
    carry = ""
    while len(line) > 1 and line[-1] in KINSOKU_TAIL:
        carry = line[-1] + carry
        line = line[:-1]
    return line, carry


def _apply_oidashi(current, wrapped):
    """新行の先頭がKINSOKU_HEADである間、前行末尾の文字を新行頭へ追い出す（前行に最低1文字残す）。"""
    while current and current[0] in KINSOKU_HEAD and wrapped and len(wrapped[-1]) > 1:
        current = wrapped[-1][-1] + current
        wrapped[-1] = wrapped[-1][:-1]
    return current


def wrap_line(draw, text, font, max_width):
    """1行のテキストを描画幅に収まるよう折り返す（ぶら下げ限定・追い出し・行末禁則・分離禁則付き）。"""
    wrapped = []
    current = ""
    for unit in _build_wrap_units(draw, text, font, max_width):
        starting_new_line = current == ""
        trial = current + unit
        w = draw.textbbox((0, 0), trial, font=font)[2]
        if w > max_width and current:
            if len(unit) == 1 and unit in BURASAGE:
                # ぶら下げ：BURASAGEのみ行幅超過を許して前行末に含める（1行につき最大1文字）
                line, carry = _trim_kinsoku_tail(current + unit)
                wrapped.append(line)
                current = carry
                continue
            # 追い出し対象の折り返し：前行を確定し、新行をunitから開始する
            line, carry = _trim_kinsoku_tail(current)
            wrapped.append(line)
            current = carry + unit
            starting_new_line = True
        else:
            current = trial
        if starting_new_line and current:
            current = _apply_oidashi(current, wrapped)
    if current:
        wrapped.append(current)
    return wrapped


def fit_font(draw, lines, font_path, max_font, max_width, max_height):
    """全行が領域に収まる最大フォントサイズと折り返し済み行を返す。"""
    fontsize = max_font
    while fontsize >= FONT_MIN:
        font = ImageFont.truetype(font_path, fontsize)
        wrapped = []
        for line in lines:
            wrapped.extend(wrap_line(draw, line, font, max_width))
        line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
        total_h = line_h * len(wrapped)
        if total_h <= max_height:
            return font, fontsize, wrapped
        fontsize -= 4
    font = ImageFont.truetype(font_path, FONT_MIN)
    wrapped = []
    for line in lines:
        wrapped.extend(wrap_line(draw, line, font, max_width))
    return font, FONT_MIN, wrapped


def draw_left_lines(draw, wrapped, font, fontsize, y_start, fill):
    """左揃えで複数行を描画する（読みの安定性を優先）。"""
    line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
    y = y_start
    for line in wrapped:
        draw.text((MARGIN, y), line, font=font, fill=fill)
        y += line_h
    return y


def split_numbering(lines):
    """ナンバリング行（安全靴と戦う12年の記録：File.XX）を本文から分離する。"""
    body_lines = []
    numbering = None
    for line in lines:
        if NUMBERING_PATTERN.search(line):
            numbering = line
        else:
            body_lines.append(line)
    return body_lines, numbering


def render_cover(draw, body_lines, numbering, font_path):
    """表紙：ダーク背景・左縦アクセント・シリーズ名／File番号を上部に配置。"""
    draw.rectangle([60, 90, 64, CANVAS_H - 90], fill=ACCENT_COLOR)
    series_font = ImageFont.truetype(font_path, 34)
    file_font = ImageFont.truetype(font_path, 44)
    series, file_no = "安全靴と戦う12年の記録", ""
    if numbering:
        parts = numbering.split("：")
        series = parts[0]
        file_no = parts[1] if len(parts) > 1 else ""
    draw.text((MARGIN, 110), series, font=series_font, fill=SUB_ON_DARK)
    if file_no:
        draw.text((MARGIN, 170), file_no, font=file_font, fill=ACCENT_COLOR)

    max_width = CANVAS_W - MARGIN * 2
    font, fontsize, wrapped = fit_font(
        draw, body_lines, font_path, COVER_FONT_MAX, max_width, int(CANVAS_H * 0.5)
    )
    line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
    y_start = (CANVAS_H - line_h * len(wrapped)) // 2 + 40
    draw_left_lines(draw, wrapped, font, fontsize, y_start, TEXT_ON_DARK)


def render_content(draw, slide, total, body_lines, font_path):
    """本文：オフホワイト背景・大きな薄番号で序列・区切り線・左揃え本文。"""
    num_font = ImageFont.truetype(font_path, 150)
    draw.text((MARGIN - 10, 100), f"{slide['number']:02d}", font=num_font, fill=NUM_COLOR)
    draw.rectangle([MARGIN, 300, MARGIN + 140, 306], fill=ACCENT_COLOR)

    max_width = CANVAS_W - MARGIN * 2
    font, fontsize, wrapped = fit_font(
        draw, body_lines, font_path, BODY_FONT_MAX, max_width, int(CANVAS_H * 0.5)
    )
    draw_left_lines(draw, wrapped, font, fontsize, 430, TEXT_ON_LIGHT)

    foot_font = ImageFont.truetype(font_path, 30)
    draw.text((MARGIN, CANVAS_H - 120), "安全靴と戦う12年の記録", font=foot_font, fill=SUB_ON_LIGHT)
    page_font = ImageFont.truetype(font_path, 34)
    page = f"{slide['number']} / {total}"
    bbox = draw.textbbox((0, 0), page, font=page_font)
    draw.text((CANVAS_W - bbox[2] - 90, CANVAS_H - 124), page, font=page_font, fill=SUB_ON_LIGHT)


def render_closing(draw, slide, total, body_lines, font_path):
    """締め：ダーク背景に戻して余韻で終える（表紙と対になる構成）。CTAは置かない。"""
    max_width = CANVAS_W - MARGIN * 2 - 20
    font, fontsize, wrapped = fit_font(
        draw, body_lines, font_path, BODY_FONT_MAX, max_width, int(CANVAS_H * 0.5)
    )
    line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
    y_start = (CANVAS_H - line_h * len(wrapped)) // 2
    y_end = draw_left_lines(draw, wrapped, font, fontsize, y_start, (240, 240, 240))
    draw.rectangle([MARGIN + 10, y_end + 40, MARGIN + 150, y_end + 46], fill=ACCENT_COLOR)

    page_font = ImageFont.truetype(font_path, 34)
    page = f"{slide['number']} / {total}"
    bbox = draw.textbbox((0, 0), page, font=page_font)
    draw.text(((CANVAS_W - bbox[2]) // 2, CANVAS_H - 120), page, font=page_font, fill=SUB_ON_DARK)


def render_slide(slide, total, ep_num, font_path, output_dir):
    img = make_background(slide["role"], CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img)
    body_lines, numbering = split_numbering(slide["lines"])

    if slide["role"] == "cover":
        render_cover(draw, body_lines, numbering, font_path)
    elif slide["role"] in ("summary", "personal_comment"):
        render_closing(draw, slide, total, body_lines, font_path)
    else:
        render_content(draw, slide, total, body_lines, font_path)

    out_path = Path(output_dir) / f"slide_{ep_num}_{slide['number']:02d}.png"
    img.save(out_path)
    return out_path


def main():
    if len(sys.argv) != 4:
        print("使用方法: generate_carousel.py <ep番号> <carousel_slides.mdパス> <出力ディレクトリ>")
        sys.exit(1)
    ep_num = sys.argv[1]
    md_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3])

    if not md_path.is_file():
        print(f"✗ 入力ファイルが見つかりません: {md_path}")
        sys.exit(1)
    output_dir.mkdir(parents=True, exist_ok=True)

    font_path = find_font_path()
    if font_path is None:
        print("✗ 日本語フォントが見つかりません（ヒラギノ／Noto CJK）")
        sys.exit(1)

    try:
        slides = parse_slides(md_path.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"✗ 解析エラー: {e}")
        sys.exit(1)

    if not (7 <= len(slides) <= 8):
        print(f"✗ スライド枚数が7〜8枚ではありません（{len(slides)}枚）")
        sys.exit(1)

    print(f"[CAROUSEL] ep{ep_num}: {len(slides)}枚のスライドを生成します")
    paths = []
    for slide in slides:
        out = render_slide(slide, len(slides), ep_num, font_path, output_dir)
        paths.append(out)
        print(f"  → {out.name}（role={slide['role']}）")
    print(f"[CAROUSEL] 完了: {len(paths)}枚 → {output_dir}")


if __name__ == "__main__":
    main()
