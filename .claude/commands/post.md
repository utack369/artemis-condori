# /post $ARGUMENTS

エピソード番号: $ARGUMENTS

## 実行手順

0. format判定：`input/instagram/ep$ARGUMENTS.json` の meta.format を確認する（フィールドがなければ reel とみなす）

### format=reel の場合

1. 以下のファイルが存在するか確認する
   - `output/instagram/ep$ARGUMENTS/episode_$ARGUMENTS_*.mp4`
   - `output/instagram/ep$ARGUMENTS/caption_$ARGUMENTS.txt`（なければ `caption.md`）
   - `output/instagram/ep$ARGUMENTS/thumbnail_$ARGUMENTS.png`（任意）

2. キャプション・動画ファイル名・サムネイル有無・予約時刻（当日20:00 JST、過ぎていれば翌日20:00）を表示し、ユーザーに確認を求める
   - 「上記の内容で予約投稿してよろしいですか？」と必ず聞く
   - ユーザーの明示的な承認なしに実行しない

3. 承認後、以下を実行する
   - `.venv/bin/python scripts/post_reel.py $ARGUMENTS`

### format=carousel の場合

1. 以下のファイルが存在するか確認する
   - `output/instagram/ep$ARGUMENTS/slides/slide_$ARGUMENTS_*.png`（7〜8枚）
   - `output/instagram/ep$ARGUMENTS/caption_$ARGUMENTS.txt`（なければ `caption.md`）

2. キャプション・スライド枚数・予約時刻（当日20:00 JST、過ぎていれば翌日20:00）を表示し、ユーザーに確認を求める
   - 「上記の内容で予約投稿してよろしいですか？」と必ず聞く
   - ユーザーの明示的な承認なしに実行しない

3. 承認後、以下を実行する
   - `.venv/bin/python scripts/post_carousel.py $ARGUMENTS`

## 結果報告（共通）

4. 結果を報告する（投稿ID・予約時刻）
