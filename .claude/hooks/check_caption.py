#!/usr/bin/env python3
# PostToolUse hook: caption形式の決定論ゲート（追補A準拠）
# captionのWriteのみ判定。ラベルなし/ep46改行/末尾LF/記録用.md==投稿用.txt を機械チェック。
# 不合格: exit 2 + stderr（Coordinator経由でαへ差し戻し）。caption以外のWriteは素通り(exit 0)。
import sys, json, re, os

def is_record_caption(p):
    return re.search(r'/output/instagram/ep\d+/caption\.md$', p) is not None

def is_post_caption(p):
    return re.search(r'caption_\d+\.txt$', p) is not None

def is_ep_json(p):
    return re.search(r'/input/instagram/ep\d+\.json$', p) is not None

def ep_of(p):
    m = re.search(r'/ep(\d+)/caption\.md$', p) or re.search(r'caption_(\d+)\.txt$', p)
    return m.group(1) if m else None

def counterpart(p, ep):
    if is_record_caption(p):
        return os.path.expanduser(f'~/Downloads/コンドリ/コンドリ動画自動生成/caption_{ep}.txt')
    return os.path.expanduser(f'~/artemis-condori/output/instagram/ep{ep}/caption.md')

def check_format(text):
    errs = []
    # 1) ラベル禁止（Markdown見出し行: # + スペース。#hashtag は対象外）
    labels = [i+1 for i, l in enumerate(text.split('\n')) if re.match(r'^#+\s', l)]
    if labels:
        errs.append(f'ラベル行が存在（行 {labels}）。`#`見出しは禁止（追補A-1）')
    # 3) 末尾は単一LF
    if not text.endswith('\n'):
        errs.append('末尾に改行がない（追補A-2）')
    elif text.endswith('\n\n'):
        errs.append('末尾に余分な空行（単一LFのみ・追補A-2）')
    # 2) 空行区切りで4ブロック（hook / body(1+) / cta / hashtags）
    body = text[:-1] if text.endswith('\n') else text
    blocks = body.split('\n\n')
    if len(blocks) != 4:
        errs.append(f'空行区切りブロック数が{len(blocks)}（期待=4: hook/body/cta/hashtags・追補A-2）')
    else:
        hook, bdy, cta, tags = blocks
        if hook.count('\n') != 0: errs.append('hookが複数行（1行であること）')
        if cta.count('\n') != 0:  errs.append('ctaが複数行（1行であること）')
        if tags.count('\n') != 0: errs.append('hashtagsが複数行（1行であること）')
        if any(l.strip() == '' for l in bdy.split('\n')):
            errs.append('body内に空行がある（追補A-2: body内に空行なし）')
    # 4) 修辞的装飾禁止記号（kazuo_honne声ルール: alpha-executor.md「修辞的装飾を使わない（——・…連鎖・比喩・文学的言い回し禁止）」）
    PROHIBITED_DECORATIONS = [
        (r'—', '——（EMダッシュ）'),
        (r'[…‥]', '…・‥（三点・二点リーダー）'),
    ]
    lines = text.split('\n')
    for pattern, label in PROHIBITED_DECORATIONS:
        hit_lines = [i+1 for i, l in enumerate(lines) if re.search(pattern, l)]
        if hit_lines:
            errs.append(f'修辞的装飾禁止記号 {label} が存在（行 {hit_lines}・kazuo_honne声ルール）')
    return errs

def check_ep_json(text):
    errs = []
    EM_DASH = '—'
    lines = text.split('\n')
    hit_lines = [i+1 for i, l in enumerate(lines) if EM_DASH in l]
    if hit_lines:
        errs.append(f'EMダッシュ（U+2014 —）が存在（行 {hit_lines}）。全フィールド禁止・代わりに読点（、）を使う')
    return errs

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    path = (payload.get('tool_input') or {}).get('file_path') or ''
    if is_ep_json(path):
        if not os.path.isfile(path):
            sys.exit(0)
        text = open(path, encoding='utf-8').read()
        errs = check_ep_json(text)
        if errs:
            sys.stderr.write('⛔ ep[N].json EMダッシュゲート不合格\n対象: ' + path + '\n')
            for e in errs:
                sys.stderr.write(' - ' + e + '\n')
            sys.stderr.write('→ EMダッシュを読点（、）に置換して再生成（alpha-executor.md参照）。\n')
            sys.exit(2)
        sys.exit(0)
    if not (is_record_caption(path) or is_post_caption(path)):
        sys.exit(0)
    if not os.path.isfile(path):
        sys.exit(0)
    text = open(path, encoding='utf-8').read()
    errs = check_format(text)
    ep = ep_of(path)
    if ep:
        cp = counterpart(path, ep)
        if os.path.isfile(cp):
            if open(cp, encoding='utf-8').read() != text:
                errs.append(f'記録用.mdと投稿用.txtが不一致（{os.path.basename(path)} vs {os.path.basename(cp)}・追補A-3: 同一内容）')
    if errs:
        sys.stderr.write('⛔ caption形式ゲート不合格（追補A）\n対象: ' + path + '\n')
        for e in errs:
            sys.stderr.write(' - ' + e + '\n')
        sys.stderr.write('→ Coordinator経由でαへ差し戻し、上記を修正（鉄則2/5）。\n')
        sys.exit(2)
    sys.exit(0)

if __name__ == '__main__':
    main()
