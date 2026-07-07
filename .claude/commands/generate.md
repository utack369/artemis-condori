Coordinator（アテナ）として、/generate 一気通貫フローを開始してください。話数 N = $ARGUMENTS。

本コマンドは段1〜段5を全自動で実行し、ep[N] の成果物と動画を output/instagram/ep[N]/ に集約します。段6（最終レビュー）は人間（うた）が行うため本フローには含めません。git push は一切行いません（うたの明示承認後・別ステップ）。以降の [N] はすべて $ARGUMENTS に読み替えてください。

## 段2：指示書JSON生成
input/instagram/ep[N].json が既に存在する場合、この段をスキップして段3に進む（事前配置済み指示書を使用）。
存在しない場合、omega① を独立 Task として起動し、指示書JSON を生成して input/instagram/ep[N].json に保存する。

## 段3：原稿・サムネ指示の生成と品質ゲート
指示書JSON を入力に alpha が caption.md / script.md / thumbnail-instruction.md を生成。Hook形式ゲートを通過させ、beta が品質チェックを行う。NG の場合は Coordinator 経由で alpha へ自動差し戻し（最大2回）。差し戻しが2回超過、または confidence < 0.7 の場合はうたへエスカレーションして停止。成果物は output/instagram/ep[N]/ に出力し、投稿用 caption_[N].txt も output/instagram/ep[N]/ に生成する（正本はここ。artemis-media側への複製は段5のcpで行う）。

### 段3-V：独立検証ゲート（artemis-verifier）
beta が pass を出した成果物に対し、Coordinator が artemis-verifier を独立 Task として起動する。alpha・beta・verifier は互いに直接通信せず、結果は必ず Coordinator に返す（鉄則②）。

**Coordinator が verifier へ明示渡しする入力（verifier は親文脈を継承しない・鉄則③）：**
- 検証対象：output/instagram/ep[N]/ の script.md / caption.md（beta 確定物・検証正本）。caption_[N].txt は投稿用の別形式のため検証対象外。
- per-ep 設定：input/instagram/ep[N].json（cta_required・numbering・euphemism 要否を含む）
- design_master 該当行：refs/design_master.md の File.[N] の1行
- 直近5作：output/instagram/ep[N-5..N-1]/script.md（I1 素材重複チェック用）

**verifier の出力：**
- refs/verification_result.schema.json の submit_verification ツールで 24 軸を pass/fail/skip で返す。
- overall（総合合否）は出力しない。集計は Coordinator が行う（鉄則⑨）。

**Coordinator の決定論的集計ルール：**
- critical または high に fail が1件以上 → Fail。omega² へ進めない。
- medium/low のみ fail → Pass 扱い。警告として記録。
- 全軸 pass または skip → Pass。

**Phase1 運用ルール（現時点）：**
Pass・Fail いずれの場合も、Coordinator は verifier 結果をうたへ提示して一旦停止する。自動リトライ・自動 post は行わない。うたの確認後、次のアクション（omega² 進行 or 差し戻し）を実行する。

**永続化：** 集計確定後、Coordinator は判定結果（verifier の24軸pass/fail/skipとCoordinatorのoverall）を直ちに output/instagram/ep[N]/verification_ep[N].json として永続化する（段5を待たない）。

**verification_ep[N].json の形式（rounds[]構造・正式定義）：**
- トップレベル：ep_number／euphemism_required／cta_required／current_round／rounds[]
- rounds[] の各要素：round（round番号）／checks[]（各軸：axis_id・axis_name・result・severity。fail の軸は target_file・location・reason・suggested_fix を必須付記）／summary（pass・fail・skip の件数）／coordinator_overall／coordinator_rule_applied／action。Pass の round には phase を付記する。
- 差し戻し後の再検証は既存 round を上書きせず、新しい round として rounds[] に追記する（履歴保全）。差し戻しゼロの ep も rounds: [{"round": 1, ...}] の形式で記録する。

### 段3-Ω：構造点検（omega²）
段3-V が Pass（Coordinator 判定）になった後に、omega² を独立 Task として起動し構造点検を行う。点検内容・出力契約は omega-instagram.md「段3 omega②」節に従う。

## 段4：動画生成
以下を実行する：
```
cd ~/artemis-condori
N=$ARGUMENTS
ARG3=$(python3 -c "import json;print('\n'.join(json.load(open('input/instagram/ep${N}.json'))['thumbnail_guideline']['selected_text']))")
python3 scripts/run_episode.py "$N" "output/instagram/ep${N}/script.md" "$ARG3"
```
- argv[2] は段3生成の script.md（素のプレーンテキスト）をそのまま渡す（変換しない）。
- argv[3] は ep[N].json の thumbnail_guideline.selected_text（配列）を \n 結合した文字列。
- 出力（固定）：~/artemis-media/コンドリ動画自動生成/ に episode_[N]_*.mp4 と thumbnail_[N].png が生成される。

## 段5：集約
以下を実行する：
```
cd ~/artemis-condori
N=$ARGUMENTS
mkdir -p output/instagram/ep${N}/
cp ~/artemis-media/コンドリ動画自動生成/episode_${N}_*.mp4 output/instagram/ep${N}/
cp ~/artemis-media/コンドリ動画自動生成/thumbnail_${N}.png output/instagram/ep${N}/
cp output/instagram/ep${N}/caption_${N}.txt ~/artemis-media/コンドリ動画自動生成/
# うた確認用：成果物フォルダをFinderで自動的に開く
open output/instagram/ep${N}
cp input/instagram/ep${N}.json output/instagram/ep${N}/
```
- mp4/png は cp（artemis-media の投稿用原本を温存）、指示書JSON は cp（input/ の原本を温存）、caption_[N].txt は cp（output/ 側の正本を artemis-media へ複製）。段5の最後に open で成果物フォルダを自動表示する。

## 完了
output/instagram/ep[N]/ の集約物一覧（caption.md / script.md / thumbnail-instruction.md / caption_[N].txt / ep[N].json / mp4 / png）をうたに提示して停止する。push は行わない。
