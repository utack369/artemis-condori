# /post $ARGUMENTS

エピソード番号: $ARGUMENTS

## 実行手順

0. format判定：`input/instagram/ep$ARGUMENTS.json` の meta.format を確認する（フィールドがなければ reel とみなす）

### format=reel の場合

1. 以下のファイルが存在するか確認する
   - `output/instagram/ep$ARGUMENTS/episode_$ARGUMENTS_*.mp4`
   - `output/instagram/ep$ARGUMENTS/caption_$ARGUMENTS.txt`（なければ `caption.md`）
   - `output/instagram/ep$ARGUMENTS/thumbnail_$ARGUMENTS.png`（任意）

2. キャプション・動画ファイル名・サムネイル有無・予約時刻（当日20:00 JST、過ぎていれば翌日20:00）を表示する（記録のため必ず表示する）
   - 本コマンドが受け渡しフォルダの本部指示ファイル（CC実行プロンプト_post*.md 等）経由で実行されている場合：本部の照合とうたの合意を経た承認済み実行とみなし、追加のユーザー確認なしで手順3に進む
   - うたがチャットで直接 /post を実行した場合（本部指示ファイル経由でない場合）：従来どおり「上記の内容で予約投稿してよろしいですか？」と確認し、明示的な承認なしに実行しない
   - イレギュラー時（対象ファイルの欠落・表示内容と成果物の不整合・前提の不一致・エラー・Hookブロック）：実行経路を問わず実行せず、停止して報告・確認を求める

3. 上記の要件を満たしたら、以下を実行する
   - `.venv/bin/python scripts/post_reel.py $ARGUMENTS`
   - 同一epのpendingが残っている場合はガードで停止する（二重投稿防止）。再投稿が必要と本部が判断した場合のみ `--force` を付ける

### format=carousel の場合

1. 以下のファイルが存在するか確認する
   - `output/instagram/ep$ARGUMENTS/slides/slide_$ARGUMENTS_*.png`（7〜8枚）
   - `output/instagram/ep$ARGUMENTS/caption_$ARGUMENTS.txt`（なければ `caption.md`）

2. キャプション・スライド枚数・予約時刻（当日20:00 JST、過ぎていれば翌日20:00）を表示する（記録のため必ず表示する）
   - 本コマンドが受け渡しフォルダの本部指示ファイル（CC実行プロンプト_post*.md 等）経由で実行されている場合：本部の照合とうたの合意を経た承認済み実行とみなし、追加のユーザー確認なしで手順3に進む
   - うたがチャットで直接 /post を実行した場合（本部指示ファイル経由でない場合）：従来どおり「上記の内容で予約投稿してよろしいですか？」と確認し、明示的な承認なしに実行しない
   - イレギュラー時（対象ファイルの欠落・表示内容と成果物の不整合・前提の不一致・エラー・Hookブロック）：実行経路を問わず実行せず、停止して報告・確認を求める

3. 上記の要件を満たしたら、以下を実行する
   - `.venv/bin/python scripts/post_carousel.py $ARGUMENTS`

## 結果報告（共通）

4. 結果を報告する（投稿ID・予約時刻）
