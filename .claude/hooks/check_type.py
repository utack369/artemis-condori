#!/usr/bin/env python3
# PreToolUse hook: ep[N].json Write 時に psychology_type を設計図マスターと照合
# 不一致: exit 2 + stderr でブロック。設計図マスター未定義エピソードは exit 0（安全側）。
import sys, json, re, os

MASTER_PATH = os.path.expanduser('~/artemis-condori/refs/design_master.md')

def is_ep_json(p):
    return re.search(r'/input/instagram/ep\d+\.json$', p) is not None

def ep_num(p):
    m = re.search(r'/ep(\d+)\.json$', p)
    return int(m.group(1)) if m else None

def get_design_type(n):
    if not os.path.isfile(MASTER_PATH):
        sys.stderr.write(f'⚠️ design_master.md が見つかりません（{MASTER_PATH}）→ Typeチェックをスキップ\n')
        return None
    key = f'File.{n:02d}'
    for line in open(MASTER_PATH, encoding='utf-8'):
        line = line.strip()
        if line.startswith(key + ' '):
            m = re.search(r'(Type_\d+)', line)
            return m.group(1) if m else None
    return None

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool_input = payload.get('tool_input') or {}
    path = tool_input.get('file_path') or ''
    if not is_ep_json(path):
        sys.exit(0)
    n = ep_num(path)
    if n is None:
        sys.exit(0)
    design_type = get_design_type(n)
    if design_type is None:
        sys.stderr.write(f'⚠️ design_master.md に File.{n:02d} の定義がありません → Typeチェックをスキップ（exit 0）\n')
        sys.exit(0)
    content = tool_input.get('content') or ''
    try:
        data = json.loads(content)
        generated_type_full = data.get('meta', {}).get('psychology_type', '')
        m = re.match(r'(Type_\d+)', generated_type_full)
        generated_type = m.group(1) if m else generated_type_full
    except Exception:
        sys.exit(0)
    if generated_type != design_type:
        sys.stderr.write(f'⛔ Type不一致：設計図={design_type}、生成={generated_type}\n')
        sys.stderr.write(f'対象: {path}\n')
        sys.stderr.write(f'→ design_master.md の File.{n:02d} を確認し、正しい Type（{design_type}）で再生成してください。\n')
        sys.exit(2)
    sys.exit(0)

if __name__ == '__main__':
    main()
