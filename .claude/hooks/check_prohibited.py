#!/usr/bin/env python3
"""PreToolUse Hook: 禁止語チェック
Write対象がep関連ファイル（ep*.json, caption*.md, script.md, caption_*.txt）の場合、
refs/prohibited_words.txt の禁止語が含まれていればexit 2でブロックする。
"""
import json, sys, os, re

def main():
    event = json.load(sys.stdin)
    tool_name = event.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    basename = os.path.basename(file_path)

    targets = (
        basename.startswith("ep") and basename.endswith(".json"),
        basename.startswith("caption"),
        basename == "script.md",
    )
    if not any(targets):
        return

    content = tool_input.get("content", "") or tool_input.get("new_string", "")
    if not content:
        return

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    words_file = os.path.join(project_dir, "refs", "prohibited_words.txt")
    if not os.path.exists(words_file):
        return

    with open(words_file, "r") as f:
        words = [line.strip() for line in f if line.strip()]

    violations = []
    for i, line in enumerate(content.splitlines(), 1):
        for word in words:
            if word in line:
                violations.append(f"  行{i}: 「{word}」検出 → {line.strip()}")

    if violations:
        msg = f"⛔ 禁止語ゲート不合格\n対象: {file_path}\n"
        msg += "\n".join(violations)
        msg += "\n→ 禁止語を削除または言い換えて再生成してください。"
        print(msg, file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
