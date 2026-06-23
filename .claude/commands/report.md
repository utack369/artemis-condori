---
allowed-tools: ["Read", "Bash"]
argument-hint: "話数（例: 11）"
---

ep$ARGUMENTS の完成報告を作成してください。

## 手順

1. 以下の2ファイルを読み取る
   - `output/instagram/ep$ARGUMENTS/script.md`
   - `input/instagram/ep$ARGUMENTS.json`

2. script.md から【ナレーション】ブロックと【テロップ】ブロックをそれぞれ抽出する
   - 【ナレーション】から次の【見出し】までの本文
   - 【テロップ】から次の【見出し】またはファイル末尾までの本文

3. ep$ARGUMENTS.json から以下の3フィールドを取得する
   - `meta.psychology_type`
   - `telop_guideline.cta_required`（true → 「あり」 / false → 「なし」）
   - `purpose`

4. 以下のフォーマットで出力する（ファイル保存不要、チャットに表示のみ）

---

```
ep$ARGUMENTS 完成報告

① ナレーション全文
（ここにscript.mdの【ナレーション】ブロック本文をそのまま表示）

② テロップ全文
（ここにscript.mdの【テロップ】ブロック本文をそのまま表示）

③ File番号・型
File.$ARGUMENTS・[psychology_type]・CTA[あり/なし]

④ シーン概要
（purposeを1行で表示）
```

## 注意事項

- 読み取り専用。ファイルの書き込み・変更は一切行わない
- script.mdの本文はそのまま表示する（要約・編集禁止）
- ファイルが存在しない場合は「ep$ARGUMENTS のファイルが見つかりません」と報告する
