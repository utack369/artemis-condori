#!/usr/bin/env python3
# PostToolUse hook: 仕事場面の普遍性ゲート（職種名 denylist・決定論層A / workplace_scene_rule）
# 台本/viewer-facing文言のWriteのみ判定。特定職種名を機械検知。
# 不合格: exit 2 + stderr（Coordinator経由でαへ差し戻し・鉄則2/5）。対象外/不在/解析失敗は exit 0。
# 曖昧な職種（医師・教師・士業等の第三者参照）は β の意味判定に委ねる（denylistに入れない）。
import sys, json, re, os

# ── 対象ファイル（viewer-facing 台本クラス）。編集可 ──
TARGET_PATTERNS = [
    r'/output/instagram/ep\d+/script\.md$',
    r'/output/instagram/ep\d+/caption\.md$',
    r'caption_\d+\.txt$',
]

# ── 職種名 denylist（決定論検知・誤検知回避の正規表現）。編集可 ──
JOB_PATTERNS = [
    (r'営業(?!時間|日|中)', '営業'),   # 「営業時間」等は除外
    (r'エンジニア',          'エンジニア'),
    (r'管理職',              '管理職'),
    (r'経理',                '経理'),
    (r'人事(?!を尽)',        '人事'),   # 「人事を尽くす」は除外
    (r'プログラマー',        'プログラマー'),
    (r'デザイナー',          'デザイナー'),
    (r'マーケター',          'マーケター'),
]

def is_target(p):
    return any(re.search(pat, p) for pat in TARGET_PATTERNS)

def find_hits(text):
    hits = []
    for i, line in enumerate(text.split('\n')):
        for pat, label in JOB_PATTERNS:
            if re.search(pat, line):
                hits.append((i + 1, label, line.strip()))
    return hits

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    path = (payload.get('tool_input') or {}).get('file_path') or ''
    if not is_target(path):
        sys.exit(0)
    if not os.path.isfile(path):
        sys.exit(0)
    text = open(path, encoding='utf-8').read()
    hits = find_hits(text)
    if hits:
        sys.stderr.write('⛔ 仕事場面の普遍性ゲート不合格（workplace_scene_rule）\n対象: ' + path + '\n')
        for ln, job, src in hits:
            sys.stderr.write(f' - 行{ln}: 職種名「{job}」を検知 → {src}\n')
        sys.stderr.write('→ 特定職種名を避け、全職種が置換できる普遍表現へ修正。Coordinator経由でαへ差し戻し（鉄則2/5）。\n')
        sys.exit(2)
    sys.exit(0)

if __name__ == '__main__':
    main()
