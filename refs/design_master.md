# 設計図マスター（Hook参照用・alpha参照用）
# check_type.py / check_cta.py が Type・CTA を照合する。
# alpha-executor が テーマ・婉曲 を参照して生成する。
# 書式: File.NN Type_N CTA:true/false 婉曲:要/不要 テーマ:（1文）
# パッケージ2（File.31〜60）のカルーセルは Type_N の代わりに Carousel:カテゴリ を記載する。
# 書式: File.NN Carousel:comparison|checklist|warning CTA:false 婉曲:要/不要 テーマ:（1文）
# 現行Hookはカルーセル行のType照合を安全にスキップする（Carousel対応Hookは第2段階で拡張予定）。
File.01 Type_2 CTA:false 婉曲:不要 テーマ:飲み会の店が座敷だと知った瞬間の絶望
File.02 Type_2 CTA:false 婉曲:要 テーマ:帰宅後、玄関で家族が一瞬黙るあの空気
File.03 Type_3 CTA:true 婉曲:要 テーマ:5本指ソックスへの期待と残酷な現実
File.04 Type_2 CTA:false 婉曲:不要 テーマ:ロッカー室で自分の靴の近くに人が来た時の緊張感
File.05 Type_2 CTA:false 婉曲:不要 テーマ:安全靴の底で一番キツかった日の話
File.06 Type_3 CTA:true 婉曲:要 テーマ:重曹足湯に毎晩30分のサンクコスト
File.07 Type_2 CTA:false 婉曲:要 テーマ:消臭スプレーと自分の汗が混ざった時のあの惨事
File.08 Type_2 CTA:false 婉曲:要 テーマ:人の家にあがる予定がある日の、朝からの憂鬱
File.09 Type_1 CTA:true 婉曲:要 テーマ:僕がゴシゴシ洗いをやめた理由
File.10 Type_2 CTA:false 婉曲:要 テーマ:妻に「気にしすぎ」と言われて余計に孤独になった夜
File.11 Type_2 CTA:false 婉曲:要 テーマ:休日のスニーカーですら誤魔化せなくなった日
File.12 Type_3 CTA:true 婉曲:要 テーマ:靴用ミョウバン水を自作して靴下が真っ白になった話
File.13 Type_2 CTA:false 婉曲:不要 テーマ:営業職には分からない、1日12時間密閉の破壊力
File.14 Type_3 CTA:true 婉曲:不要 テーマ:市販クリームを塗りすぎて足が滑るだけの無意味な時間
File.15 Type_1 CTA:true 婉曲:要 テーマ:靴を2足買って毎日ローテーションした結果の限界
File.16 Type_2 CTA:false 婉曲:不要 テーマ:外回りの後、こっそりトイレで靴下を履き替える儀式
File.17 Type_3 CTA:true 婉曲:不要 テーマ:制汗剤の使いすぎで足裏がカサカサになった失敗談
File.18 Type_3 CTA:true 婉曲:要 テーマ:「体質だから」で諦めていた12年間の思考停止
File.19 Type_1 CTA:true 婉曲:要 テーマ:毎日インソールを変えても昼には限界が来る理由
File.20 Type_1 CTA:true 婉曲:不要 テーマ:「通気性抜群」という謳い文句に対する現場の答え
File.21 Type_1 CTA:true 婉曲:不要 テーマ:「洗えば落ちる」という思い込みが招いた二次被害
File.22 Type_1 CTA:true 婉曲:不要 テーマ:現場作業員の安全靴という「特殊環境」の無視
File.23 Type_2 CTA:false 婉曲:要 テーマ:夏より冬の暖房の効いた車内の方が地獄という真実
File.24 Type_1 CTA:true 婉曲:不要 テーマ:安全靴8時間後、靴の中の湿度を調べた
File.25 Type_1 CTA:true 婉曲:不要 テーマ:足裏の角質ケアパックで根本解決しなかった理由
File.26 Type_1 CTA:true 婉曲:要 テーマ:香りで誤魔化す系アイテムの末路はいつも同じ
File.27 Type_3 CTA:true 婉曲:不要 テーマ:努力の方向を「外側」から「内側」に変えた日のこと
File.28 Type_1 CTA:true 婉曲:要 テーマ:12年で試した対策、正直に全部言います
File.29 Type_1 CTA:true 婉曲:要 テーマ:やって無駄だった対策ワースト3
File.30 Type_1 CTA:true 婉曲:不要 テーマ:魔法はない。ただ、毎日の絶望感はリセットできる
# ===== パッケージ2（File.31〜60）出典: refs/condori_pkg2_design_complete.md =====
File.31 Type_2 CTA:false 婉曲:要 テーマ:同僚に「お前、足大丈夫か」と言われた日の沈黙
File.32 Type_2 CTA:false 婉曲:不要 テーマ:工場の休憩室で靴を脱げないまま過ごす昼休み
File.33 Type_1 CTA:true 婉曲:不要 テーマ:新品の安全靴が1週間で同じ状態になる絶望
File.34 Carousel:comparison CTA:false 婉曲:不要 テーマ:12年で試した足元対策、正直に並べてみた
File.35 Type_3 CTA:true 婉曲:要 テーマ:消臭パウダーに賭けた3ヶ月と粉だらけの靴下
File.36 Type_2 CTA:false 婉曲:要 テーマ:出張先のホテルで靴を廊下に出した夜
File.37 Carousel:checklist CTA:false 婉曲:不要 テーマ:安全靴で足がやられる人の共通点5つ
File.38 Type_1 CTA:true 婉曲:不要 テーマ:安全靴メーカーに問い合わせた時の的外れな回答
File.39 Type_3 CTA:true 婉曲:不要 テーマ:爪の間のケアにハマって2ヶ月で諦めた理由
File.40 Carousel:warning CTA:false 婉曲:不要 テーマ:実は足を悪化させていた日常習慣3つ
File.41 Type_1 CTA:true 婉曲:要 テーマ:足用石鹸3種を使い比べた正直な感想
File.42 Type_2 CTA:false 婉曲:要 テーマ:子どもに足のことを言われた日の帰り道
File.43 Type_1 CTA:true 婉曲:不要 テーマ:車に安全靴を一晩置き忘れた翌朝、密閉の本質を知った
File.44 Carousel:comparison CTA:false 婉曲:不要 テーマ:足用石鹸・スプレー・パウダー 正直な使い分けガイド
File.45 Type_3 CTA:true 婉曲:不要 テーマ:竹炭インソールに期待した2ヶ月間
File.46 Type_1 CTA:true 婉曲:不要 テーマ:革靴と安全靴で次元が違う理由を現場から説明する
File.47 Carousel:checklist CTA:false 婉曲:不要 テーマ:足元の対策に12年でいくら使ったか計算してみた
File.48 Type_2 CTA:false 婉曲:要 テーマ:銭湯に行けなくなった年のこと
File.49 Type_3 CTA:true 婉曲:不要 テーマ:足湯マッサージ器を買って1ヶ月で棚に置いた話
File.50 Carousel:warning CTA:false 婉曲:不要 テーマ:安全靴ユーザーが見落としがちな落とし穴3つ
File.51 Type_2 CTA:false 婉曲:不要 テーマ:夏場の安全靴の中が水たまりになる日の話
File.52 Type_1 CTA:true 婉曲:要 テーマ:靴下を黒にした本当の理由
File.53 Type_3 CTA:true 婉曲:不要 テーマ:通販で買った消臭グッズが全部ハズレだった話
File.54 Carousel:comparison CTA:false 婉曲:不要 テーマ:市販消臭アイテム5種 コストと持続時間の正直な比較
File.55 Type_2 CTA:false 婉曲:要 テーマ:仕事終わりの居酒屋で座敷を断り続けた3年間
File.56 Type_1 CTA:true 婉曲:不要 テーマ:足裏の皮がむける原因を自分なりに調べた結果
File.57 Carousel:checklist CTA:false 婉曲:不要 テーマ:外側の対策を12年試した僕の結論チェックリスト
File.58 Type_3 CTA:true 婉曲:不要 テーマ:足指パッドを3種類試して全部やめた理由
File.59 Type_2 CTA:false 婉曲:要 テーマ:妻が靴箱の消臭剤を無言で2つに増やした日
File.60 Carousel:warning CTA:false 婉曲:不要 テーマ:12年の記録で分かった、やめた方がいい対策の共通パターン
