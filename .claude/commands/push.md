# /push $ARGUMENTS

エピソード番号: $ARGUMENTS

## 実行手順

1. 以下のファイルをステージングする
   - `output/instagram/ep$ARGUMENTS/` 配下の全ファイル
   - `input/instagram/ep$ARGUMENTS.json`（存在する場合）

2. `git status` でステージング内容を表示し、ユーザーに確認を求める
   - 「上記の内容でcommit & pushしてよろしいですか？」と必ず聞く
   - ユーザーの明示的な承認なしにcommit/pushしない

3. 承認後、以下を実行する
   - `git commit -m "feat: File.$ARGUMENTS 生成完了"`
   - `git push`

4. 結果を報告する
