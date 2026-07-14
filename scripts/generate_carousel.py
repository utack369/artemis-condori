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
BG_COLOR = (244, 244, 242)        # 白グレー
TEXT_COLOR = (43, 43, 43)         # 濃グレー
SUB_COLOR = (120, 120, 120)       # 薄グレー（ナンバリング・ページ表示）
ACCENT_COLOR = (60, 60, 60)       # 表紙の帯
MARGIN_RATIO = 0.10               # 左右余白
TEXT_AREA_RATIO = 0.80            # テキスト幅の上限（画面比）
COVER_FONT_MAX = 96
BODY_FONT_MAX = 72
FONT_MIN = 36
LINE_SPACING_RATIO = 0.45         # 行間（フォントサイズ比）
WRAP_MEASURE_STEP = 1

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",   # 本番Mac（太）
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",   # 本番Mac（細）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",     # 検証環境
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

NUMBERING_PATTERN = re.compile(r"安全靴と戦う12年の記録：File\.\d+")
BLOCK_PATTERN = re.compile(r"【スライド(\d+)｜(\w+)】")


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
    """背景画像を返す。将来のGemini API背景生成はこの関数の差し替えで対応する。"""
    return Image.new("RGB", (width, height), BG_COLOR)


def wrap_line(draw, text, font, max_width):
    """1行のテキストを描画幅に収まるよう文字単位で折り返す。"""
    wrapped = []
    current = ""
    for ch in text:
        trial = current + ch
        w = draw.textbbox((0, 0), trial, font=font)[2]
        if w > max_width and current:
            wrapped.append(current)
            current = ch
        else:
            current = trial
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


def draw_centered_lines(draw, wrapped, font, fontsize, y_start, canvas_w):
    line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
    y = y_start
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (canvas_w - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        y += line_h
    return y


def render_slide(slide, total, ep_num, font_path, output_dir):
    is_cover = slide["role"] == "cover"
    img = make_background(slide["role"], CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img)

    # ナンバリング行（表紙）を本文から分離
    body_lines = []
    numbering = None
    for line in slide["lines"]:
        if NUMBERING_PATTERN.search(line):
            numbering = line
        else:
            body_lines.append(line)

    max_width = int(CANVAS_W * TEXT_AREA_RATIO)
    max_height = int(CANVAS_H * 0.55)
    max_font = COVER_FONT_MAX if is_cover else BODY_FONT_MAX

    font, fontsize, wrapped = fit_font(
        draw, body_lines, font_path, max_font, max_width, max_height
    )
    line_h = fontsize + int(fontsize * LINE_SPACING_RATIO)
    total_h = line_h * len(wrapped)
    y_start = (CANVAS_H - total_h) // 2
    draw_centered_lines(draw, wrapped, font, fontsize, y_start, CANVAS_W)

    sub_font = ImageFont.truetype(font_path, 34)

    if is_cover:
        # 表紙：上部に帯、下部にナンバリング
        draw.rectangle([0, 0, CANVAS_W, 14], fill=ACCENT_COLOR)
        if numbering:
            bbox = draw.textbbox((0, 0), numbering, font=sub_font)
            x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
            draw.text((x, CANVAS_H - 140), numbering, font=sub_font, fill=SUB_COLOR)
    else:
        # 本文・締め：下部中央にページ表示
        page = f"{slide['number']} / {total}"
        bbox = draw.textbbox((0, 0), page, font=sub_font)
        x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
        draw.text((x, CANVAS_H - 110), page, font=sub_font, fill=SUB_COLOR)

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
