---
name: generate
description: "Instagramエピソード(epXX)の4成果物と動画を段1から段5まで一気通貫生成する。/generate [N] (Nはエピソード番号) で明示起動して使う。"
disable-model-invocation: true
---

# /generate — 正本参照（Single Source of Truth）

このスキルの実体フローは `.claude/commands/generate.md` が唯一の正本（SSOT）です。

## 実行手順

1. `.claude/commands/generate.md` を読み込む
2. そこに記載された全段階（段1〜段5。段2の既存JSON分岐・段3・段3-V独立検証ゲート・段3-Ω構造点検・段4・段5・Downloads cp を含む）を、省略・改変・取捨選択せずそのまま実行する

## 禁止事項

- 本ファイルにフローの複製を書かないこと（二重管理による乖離の再発防止。commit 7018ad7 で generate.md のみ更新され本ファイルへの反映が漏れた事故が根拠）
- フローの改修は generate.md 側のみで行うこと
