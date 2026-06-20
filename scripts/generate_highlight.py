#!/Users/utano/artemis-condori/.venv/bin/python3
"""
ハイライト画像生成スクリプト
背景画像（テキストなし）にメインテキスト・サブテキストを描画して出力する。

使い方:
  python3 generate_highlight.py \
    --main "どれだけ寝ても/朝から体が/重い" \
    --highlight "重い" \
    --sub "または/週末に休んでも/月曜にはもう動けない" \
    --output 2.png
"""

import argparse
import os
from PIL import Image, ImageDraw, ImageFont

HOME = os.path.expanduser("~")
DEFAULT_BG = os.path.join(HOME, "Downloads/インスタ/インスタハイライト背景画像/背景1.jpg")
DEFAULT_OUTPUT_DIR = os.path.join(HOME, "Downloads/インスタ/インスタハイライト画像")
CANVAS_W = 1080
CANVAS_H = 1920
FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
FONT_LIGHT = "/System/Library/Fonts/ヒラギノ角ゴシック W1.ttc"
COLOR_WHITE = (255, 255, 255)
COLOR_GOLD_DEFAULT = (210, 180, 110)


def load_font(font_path, size):
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    fallback = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    if os.path.exists(fallback):
        return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


def calc_fontsize(draw, lines, font_path, max_width, start_size=130, min_size=50):
    for size in range(start_size, min_size - 1, -2):
        font = load_font(font_path, size)
        fits = True
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] > max_width:
                fits = False
                break
        if fits:
            return size, font
    return min_size, load_font(font_path, min_size)


def draw_main_text(draw, lines, highlight_word, gold_color, font, y_start):
    line_spacing = int(font.size * 0.3)
    for line in lines:
        bbox_full = draw.textbbox((0, 0), line, font=font)
        line_w = bbox_full[2] - bbox_full[0]
        x = (CANVAS_W - line_w) // 2
        if highlight_word and highlight_word in line:
            parts = line.split(highlight_word)
            cursor_x = x
            for i, part in enumerate(parts):
                if part:
                    draw.text((cursor_x, y_start), part, font=font, fill=COLOR_WHITE)
                    part_bbox = draw.textbbox((0, 0), part, font=font)
                    cursor_x += part_bbox[2] - part_bbox[0]
                if i < len(parts) - 1:
                    draw.text((cursor_x, y_start), highlight_word, font=font, fill=gold_color)
                    hl_bbox = draw.textbbox((0, 0), highlight_word, font=font)
                    cursor_x += hl_bbox[2] - hl_bbox[0]
        else:
            draw.text((x, y_start), line, font=font, fill=COLOR_WHITE)
        line_h = bbox_full[3] - bbox_full[1]
        y_start += line_h + line_spacing
    return y_start


def draw_sub_text(draw, lines, font, y_start):
    line_spacing = int(font.size * 0.4)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        x = (CANVAS_W - line_w) // 2
        draw.text((x, y_start), line, font=font, fill=COLOR_WHITE)
        y_start += line_h + line_spacing
    return y_start


def generate_highlight(bg_path, main_lines, highlight_word, sub_lines, output_path, gold_color):
    bg = Image.open(bg_path).convert("RGB")
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
    draw = ImageDraw.Draw(bg)
    max_width = int(CANVAS_W * 0.85)
    main_fontsize, main_font = calc_fontsize(draw, main_lines, FONT_BOLD, max_width, start_size=130, min_size=50)
    sub_fontsize = max(int(main_fontsize * 0.55), 24)
    sub_font = load_font(FONT_LIGHT, sub_fontsize)
    main_line_spacing = int(main_font.size * 0.3)
    main_total_h = 0
    for line in main_lines:
        bbox = draw.textbbox((0, 0), line, font=main_font)
        main_total_h += (bbox[3] - bbox[1]) + main_line_spacing
    main_total_h -= main_line_spacing
    main_y = int(CANVAS_H * 0.35) - main_total_h // 2 + int(CANVAS_H * 0.05)
    main_end_y = draw_main_text(draw, main_lines, highlight_word, gold_color, main_font, main_y)
    sub_y = main_end_y + int(CANVAS_H * 0.08)
    draw_sub_text(draw, sub_lines, sub_font, sub_y)
    bg.save(output_path, "PNG")
    print(f"✅ ハイライト画像生成完了: {output_path}")
    print(f"   メイン: {' / '.join(main_lines)}")
    print(f"   強調語: {highlight_word} (ゴールド)")
    print(f"   サブ:   {' / '.join(sub_lines)}")


def main():
    parser = argparse.ArgumentParser(description="ハイライト画像生成")
    parser.add_argument("--main", required=True, help="メインテキスト（行区切り: /）")
    parser.add_argument("--highlight", default="", help="ゴールド強調する語")
    parser.add_argument("--sub", required=True, help="サブテキスト（行区切り: /）")
    parser.add_argument("--output", required=True, help="出力ファイル名（例: 2.png）")
    parser.add_argument("--bg", default=DEFAULT_BG, help="背景画像パス")
    parser.add_argument("--gold", default=None, help="ゴールド色 hex（例: #D2B46E）")
    args = parser.parse_args()
    main_lines = [line.strip() for line in args.main.split("/") if line.strip()]
    sub_lines = [line.strip() for line in args.sub.split("/") if line.strip()]
    if args.gold:
        hex_color = args.gold.lstrip("#")
        gold_color = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    else:
        gold_color = COLOR_GOLD_DEFAULT
    output_path = os.path.join(DEFAULT_OUTPUT_DIR, args.output)
    if not os.path.exists(args.bg):
        print(f"❌ 背景画像が見つかりません: {args.bg}")
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    generate_highlight(args.bg, main_lines, highlight_word=args.highlight,
                       sub_lines=sub_lines, output_path=output_path, gold_color=gold_color)


if __name__ == "__main__":
    main()
