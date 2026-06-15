Coordinator（アテナ）として、/instagram実行フローを開始してください。

## 参照すべきサブエージェント定義
- @.claude/agents/omega-instagram.md
- @.claude/agents/alpha-executor.md
- @.claude/agents/beta-executor.md
- @.claude/agents/delta-researcher.md

## 実行フロー（CLAUDE.mdに定義済みの9ステップ）
CLAUDE.mdの「/instagram 実行フロー」セクションに従い、
Coordinator主導で以下を順番に実行すること。

1. Ω（アルテミス）にJSON指示書の解析・実行指示の組み立てを委任
2. α（実行員α）に原稿生成を委任
3. β（実行員β）に品質チェックを委任
4. うたに承認を求める
5. 承認後、αにGitHub pushを委任

## エスカレーション基準（明示的トリガー）
- Ωの確信度が0.7未満のとき
- βが2回差し戻したとき
- JSON指示書に未定義フィールドがあったとき

指示内容: $ARGUMENTS
