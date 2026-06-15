Coordinator（アテナ）として、/generate 一気通貫フローを開始してください。話数 N = $ARGUMENTS。

本コマンドは段1〜段5を全自動で実行し、ep[N] の成果物と動画を output/instagram/ep[N]/ に集約します。段6（最終レビュー）は人間（うた）が行うため本フローには含めません。git push は一切行いません（うたの明示承認後・別ステップ）。以降の [N] はすべて $ARGUMENTS に読み替えてください。

## 段2：指示書JSON生成
input/instagram/ep[N].json が既に存在する場合、この段をスキップして段3に進む（事前配置済み指示書を使用）。
存在しない場合、omega① を独立 Task として起動し、指示書JSON を生成して input/instagram/ep[N].json に保存する。

## 段3：原稿・サムネ指示の生成と品質ゲート
指示書JSON を入力に alpha が caption.md / script.md / thumbnail-instruction.md を生成。Hook形式ゲートを通過させ、beta が品質チェック、omega² が構造点検。NG の場合は Coordinator 経由で alpha へ自動差し戻し（最大2回）。差し戻しが2回超過、または confidence < 0.7 の場合はうたへエスカレーションして停止。成果物は output/instagram/ep[N]/ に出力し、投稿用 caption_[N].txt も作成する。

## 段4：動画生成
以下を実行する：
```
cd ~/artemis-condori
N=$ARGUMENTS
ARG3=$(python3 -c "import json;print('\n'.join(json.load(open('input/instagram/ep${N}.json'))['thumbnail_guideline']['selected_text']))")
python3 ~/Downloads/コンドリ/動画自動化/scripts/run_episode.py "$N" "output/instagram/ep${N}/script.md" "$ARG3"
```
- argv[2] は段3生成の script.md（素のプレーンテキスト）をそのまま渡す（変換しない）。
- argv[3] は ep[N].json の thumbnail_guideline.selected_text（配列）を \n 結合した文字列。
- 出力（固定）：~/Downloads/コンドリ/コンドリ動画自動生成/ に episode_[N]_*.mp4 と thumbnail_[N].png が生成される。

## 段5：集約
以下を実行する：
```
cd ~/artemis-condori
N=$ARGUMENTS
mkdir -p output/instagram/ep${N}/
cp ~/Downloads/コンドリ/コンドリ動画自動生成/episode_${N}_*.mp4 output/instagram/ep${N}/
cp ~/Downloads/コンドリ/コンドリ動画自動生成/thumbnail_${N}.png output/instagram/ep${N}/
cp output/instagram/ep${N}/caption_${N}.txt ~/Downloads/コンドリ/コンドリ動画自動生成/
cp input/instagram/ep${N}.json output/instagram/ep${N}/
```
- mp4/png は cp（Downloads の投稿用原本を温存）、指示書JSON は cp（input/ の原本を温存）。

## 完了
output/instagram/ep[N]/ の集約物一覧（caption.md / script.md / thumbnail-instruction.md / caption_[N].txt / ep[N].json / mp4 / png）をうたに提示して停止する。push は行わない。
