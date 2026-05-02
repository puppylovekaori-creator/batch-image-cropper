人物画像ZIP前処理 GUI
====================

概要
----
Windows 11 向けの、人物画像ZIPをローカルで前処理する GUI アプリです。
ZIP を 1 件ずつ展開し、OpenCV の顔検出とブレ量から selected_candidate / review / exclude に機械分類します。

重要:
- selected_candidate は core確定ではありません。
- review も人間確認対象です。
- 本人判定は絶対に自動確定しません。


納品物
------
- main.py
- config.json
- requirements.txt
- run.bat
- README.txt


起動方法
--------
1. run.bat をダブルクリックしてください。
2. GUI が開いたら、各フォルダと閾値を設定してください。
3. 必要なら「設定保存」で config.json に保存してください。
4. 「処理開始」を押すと、入力ZIPフォルダ直下の .zip をファイル名昇順で処理します。


初回セットアップ
----------------
Python 3 が入っていない場合は先にインストールしてください。

推奨コマンド:
py -3 -m pip install -r requirements.txt

この端末では Python 3.14 + tkinter + Pillow + OpenCV で動作確認しています。
もし別の Python が既定になっていて依存関係が入らない場合は、明示的に次のように指定してください。

py -3.14 -m pip install -r requirements.txt


GUI項目説明
-----------
入力ZIPフォルダ:
- 処理対象の .zip を置くフォルダです。
- 直下の .zip のみ対象です。サブフォルダの .zip は拾いません。

出力フォルダ:
- ZIPごとの結果フォルダ、result.zip、logs フォルダを作成します。
- 入力ZIPフォルダと同じパスは指定できません。

一時フォルダ:
- ZIP 展開用の作業フォルダです。
- ZIP ごとに個別のサブフォルダを自動生成します。

処理済みZIP移動先フォルダ:
- 「処理済みZIPをdoneへ移動」が ON のときだけ使います。
- 成功した ZIP だけ移動します。

selected用 最小顔比率:
- 最大顔矩形面積 ÷ 画像全体面積 のしきい値です。
- これ以上なら selected_candidate 候補に入りやすくなります。

review用 最小顔比率:
- これ未満の顔サイズは exclude 寄りになります。
- selected用 より小さい値にしてください。

ブレ閾値:
- OpenCV の Laplacian 分散値です。
- 値が大きいほど鮮明寄りです。

contact sheet列数:
- contact sheet の横並び列数です。

サムネイル幅:
- contact sheet の各画像幅です。

処理済みZIPをdoneへ移動:
- 成功した ZIP のみ done へ移動します。
- 失敗ZIPは入力フォルダに残します。

一時フォルダを処理後削除:
- ON なら ZIP ごとの展開フォルダを最後に削除します。
- 調査用に残したい場合は OFF にしてください。

既存出力を上書き:
- OFF の場合、同名結果フォルダが既にある ZIP はスキップします。
- ON の場合、同名結果フォルダを削除して再作成します。

exclude画像もコピーする:
- ON の場合は exclude フォルダにも画像をコピーします。
- OFF の場合でも report と contact sheet には exclude 情報を残します。

処理開始:
- バッチ処理を開始します。

停止要求:
- 現在の ZIP 処理が終わった後で安全停止します。
- 処理途中の ZIP は最後まで完了させます。

設定保存 / 設定読込:
- config.json に保存・復元します。


判定基準
--------
前提:
- 顔検出は OpenCV Haar Cascade を使用します。
- 顔比率は「最大顔矩形面積 ÷ 画像面積」です。
- ブレ値は Laplacian 分散です。

selected_candidate:
- 正面顔を 1 つ検出
- 顔比率が selected用 最小顔比率以上
- ブレ値がブレ閾値以上
- 端寄りや極端な明暗でない

review:
- 顔はあるが selected_candidate には弱い
- 顔がやや小さい
- ブレがやや強い
- 顔が端寄り
- 横顔や角度付き顔

exclude:
- 顔なし
- 複数顔
- 顔が review 用しきい値未満
- 強いブレ
- 破損画像
- 横顔候補でも小さすぎる、またはブレが強い

注意:
- この判定は機械的なふるい分けです。
- selected_candidate に入っても本人確定ではありません。
- review は捨て枠ではなく、人間確認候補です。


処理内容
--------
1. 入力フォルダ内の .zip をファイル名昇順で処理します。
2. ZIP を一時フォルダ配下の個別サブフォルダへ展開します。
3. 画像を再帰走査します。
4. 顔数、顔比率、ブレ量から分類します。
5. selected_candidate / review / exclude に振り分けます。
6. contact_sheet_all.jpg / contact_sheet_selected_candidate.jpg / contact_sheet_review.jpg を生成します。
7. selection_report.txt を生成します。
8. 結果フォルダ全体を ZIP 化して *_result.zip を作成します。
9. 成功時のみ done フォルダへ元 ZIP を移動します。
10. 設定に応じて一時フォルダを削除します。


出力構成
--------
OutputFolder\
  logs\
    zip_preprocess_YYYYMMDD_HHMMSS.log
  kaori_009\
    selected_candidate\
    review\
    exclude\
    contact_sheet_all.jpg
    contact_sheet_selected_candidate.jpg
    contact_sheet_review.jpg
    selection_report.txt
    kaori_009_result.zip

selection_report.txt には次を出力します。
- 元ZIP名
- 総画像数
- selected_candidate数
- review数
- exclude数
- 各画像の分類理由
- 顔数
- 顔比率
- ブレ値
- 使用設定
- 開始/終了時刻
- エラー内容


ログ
----
- OutputFolder\logs\ に日時付きログを出力します。
- GUIログ欄にも同じ内容を表示します。
- 1ZIP で失敗しても全体処理は継続します。


よくあるエラーと対処
--------------------
1. OpenCV の読み込みに失敗しました
- py -3 -m pip install -r requirements.txt を実行してください。
- 複数 Python がある場合は py -3.14 -m pip install -r requirements.txt を試してください。

2. 入力ZIPフォルダと出力フォルダを同じパスにはできません
- 入力と出力を別フォルダにしてください。

3. 既存出力があるためスキップしました
- 同名 ZIP の前回結果が残っています。
- 上書きしたい場合は「既存出力を上書き」を ON にしてください。

4. 破損ZIPの可能性があります
- ZIP が壊れているか、Windows 側で解凍できない形式の可能性があります。
- ログと selection_report.txt を確認してください。

5. 顔検出が弱い / selected_candidate が少ない
- selected用 最小顔比率を下げる
- review用 最小顔比率を下げる
- ブレ閾値を下げる
- ただし、下げるほど review / selected_candidate にノイズが増えます

6. 日本語ファイル名で一部名前が変わる
- ZIP 内部の文字コードや Windows 禁止文字の都合で、安全側に名前を補正して展開する場合があります。


補足
----
- run.bat はダブルクリック起動用です。
- main.py 直接起動でも動きます。
- GUI生成だけ確認したい場合は次を実行してください。

py -3 main.py --headless-smoke-test
