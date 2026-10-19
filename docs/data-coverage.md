# 鉄道データの対応範囲

確認日: 2026-10-19。データカタログ上の提供状況と、アプリの対応範囲は区別します。運行日・区間・データの欠損等により経路が返らない場合があります。時刻表ベースであり、リアルタイム情報は取得しません。

## アダプターで許可する事業者

|事業者|ODPT識別子|利用条件|接続方法|
|---|---|---|---|
|東京都交通局|Toei|CC BY 4.0|公開 API、キー不要|
|東京メトロ|TokyoMetro|ODPT基本ライセンス|無料登録キー|
|東京臨海高速鉄道（りんかい線）|TWR|ODPT基本ライセンス|無料登録キー|
|首都圏新都市鉄道（つくばエクスプレス）|MIR|ODPT基本ライセンス|無料登録キー|
|多摩都市モノレール|TamaMonorail|ODPT基本ライセンス|無料登録キー|
|ゆりかもめ（条件付き）|Yurikamome|ODPT基本ライセンス|無料登録キー＋駅時刻表補完を明示選択|

ゆりかもめを除く上記事業者は、カタログで列車時刻表・運賃の提供を確認しています。ゆりかもめは駅時刻表・運賃が提供され、安定した列車IDが実際の応答で確認できる便に限り補完の対象です。キー付き実データでの利用可能性は未検証です。登録用のキーはサーバーの環境変数に設定し、ブラウザーや Git に保存しません。基本ライセンスの生データは公開リポジトリに再配布しません。

カタログの列車時刻表・運賃:
- 都営: https://ckan.odpt.org/dataset/r_train_timetable-toei / https://ckan.odpt.org/dataset/r_fare-toei
- 東京メトロ: https://ckan.odpt.org/dataset/r_train_timetable-tokyometro / https://ckan.odpt.org/dataset/r_fare-tokyometro
- りんかい線: https://ckan.odpt.org/dataset/r_train_timetable-twr / https://ckan.odpt.org/dataset/r_fare-twr
- つくばエクスプレス: https://ckan.odpt.org/dataset/r_train_timetable-mir / https://ckan.odpt.org/dataset/r_fare-mir
- 多摩モノレール: https://ckan.odpt.org/dataset/r_train_timetable-tamamonorail / https://ckan.odpt.org/dataset/r_fare-tamamonorail

## 自動利用しない事業者・データ

|事業者|確認できたデータ|採用していない理由|
|---|---|---|
|京王・東武|列車時刻表・運賃|チャレンジ2026限定条件|
|東急・西武・京急|駅時刻表・運賃|チャレンジ限定、列車時刻表未確認|
|小田急|駅時刻表|チャレンジ限定、列車時刻表・運賃未確認|
|JR東日本|列車時刻表|チャレンジ限定、運賃未確認|
|京成|未確認|未対応|

駅時刻表だけから、列車が別駅へ何分で着くかを推測して実データとして扱いません。チャレンジ2026のデータには参加条件と2027年3月12日までの期限があるため、通常運用の既定データにはしません。

カタログ: https://ckan.odpt.org/dataset/?organization=keio / https://ckan.odpt.org/dataset/?organization=tobu / https://ckan.odpt.org/dataset/?organization=tokyu / https://ckan.odpt.org/dataset/?organization=seibu / https://ckan.odpt.org/dataset/?organization=keikyu / https://ckan.odpt.org/dataset/?organization=odakyu / https://ckan.odpt.org/dataset/?organization=jreast

ライセンス:
- https://developer.odpt.org/terms/data_basic_license.html
- https://creativecommons.org/licenses/by/4.0/
- https://developer.odpt.org/challenge_license
- https://challenge2025.odpt.org/materials/webinar01-01-3.pdf

## 運賃・乗換に関する制限

大人普通現金運賃を扱います。同じ事業者内の経路でも、乗車駅から降車駅までの公開運賃が確認できる場合だけ使用します。隣接駅の運賃を足し合わせません。事業者をまたぐ通し運賃、乗継割引、特急・座席指定などの追加料金は扱いません。未確定の経路は最適化対象から外し、除外を表示します。

乗換徒歩時間の実測平均は取得していません。アプリの仮定値と時刻表上の接続待ちを明確に区別します。
