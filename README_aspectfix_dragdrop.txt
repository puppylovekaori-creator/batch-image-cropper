画像アスペクト補正 GUI
======================

概要
----
Windows 11 向けの、画像内容そのものの横伸び・縦伸びを補正して保存する GUI アプリです。
主目的は人物比率の歪み補正であり、16:9 化やぼかし背景は保存時の仕上げ処理です。
元画像は絶対に上書きせず、必ず `OutputFolder` 配下へ別名保存します。


納品物
------
- aspectfix_dragdrop_gui.py
- aspectfix_dragdrop_config.json
- requirements_aspectfix.txt
- run_aspectfix_dragdrop.bat
- README_aspectfix_dragdrop.txt


基本操作
--------
1. `run_aspectfix_dragdrop.bat` をダブルクリックして起動します。
2. エクスプローラーで画像ファイルを複数選択します。
3. GUI の大きなドロップ領域へドラッグ＆ドロップします。
4. `内容の歪み補正` で横倍率 / 縦倍率を調整します。
5. 必要なら `保存時のキャンバス処理` を追加します。
6. `プレビュー更新` で別ウィンドウの補正前 / 補正後を確認します。
7. `処理開始` を押してリスト内画像だけを一括処理します。


初回セットアップ
----------------
Python 3 が入っていない場合は先にインストールしてください。

推奨コマンド:
py -3 -m pip install -r requirements_aspectfix.txt

`tkinterdnd2` が入っていればドラッグ＆ドロップが有効になります。
入っていなくても、`ファイル追加` ボタンから複数画像を追加できます。


起動
----
- 推奨: `run_aspectfix_dragdrop.bat`
- 直接起動: `py -3 aspectfix_dragdrop_gui.py`
- GUI 生成確認: `py -3 aspectfix_dragdrop_gui.py --headless-smoke-test`


処理の考え方
------------
1. 内容補正
- 画像内容そのものを `XScale / YScale` で変形します。
- 横伸び・縦伸びを直すには `内容の歪み補正` の横倍率 / 縦倍率を使います。
- 例:
  - 横に太く見える画像: `XScale=0.95, YScale=1.0`
  - 縦に長く見える画像: `XScale=1.0, YScale=0.95`

2. 保存時のキャンバス処理
- 内容補正後の画像を、どの枠で保存するかを決めます。
- `保存キャンバス比率` や `ぼかし背景` は仕上げ処理であり、人物比率の補正ではありません。
- `16:9キャンバスに配置` は、見た目の枠を整えるだけです。


初期値
------
- 内容補正プリセット: `横を縮める 95%`
- 横倍率: `0.95`
- 縦倍率: `1.0`
- 保存時のキャンバス処理: `内容サイズのまま保存`


GUI項目
-------
1. 内容の歪み補正
- 横倍率
- 縦倍率
- プリセット
  - 横を少し縮める 98%
  - 横を縮める 95%
  - 横を強めに縮める 90%
  - 縦を少し縮める 98%
  - 縦を縮める 95%
  - 変更なし

2. 保存時のキャンバス処理
- 保存キャンバス処理
  - 内容サイズのまま保存
  - 元画像サイズに合わせる
  - 元画像サイズに中央クロップ
  - 16:9キャンバスに配置
- 保存キャンバス比率
- 余白の埋め方
  - 余白色
  - ぼかし背景
- 余白色

プレビュー
- 左: 補正前
- 右: 内容補正後
- キャンバス処理が無効なときは `内容補正のみ`
- キャンバス処理が有効なときは `内容補正 + キャンバス処理`
- 右側は別ウィンドウで表示します。


設定ファイル
------------
初期 `aspectfix_dragdrop_config.json` は次の内容です。

```json
{
  "OutputFolder": "C:\\output_aspect_fixed",
  "RecursiveFolderDrop": true,
  "KeepFolderStructureWhenFolderAdded": false,
  "Extensions": [".jpg", ".jpeg", ".png", ".webp", ".bmp"],
  "Mode": "manual_scale",
  "ContentPreset": "横を縮める 95%",
  "XScale": 0.95,
  "YScale": 1.0,
  "CanvasProcessing": "content_only",
  "SaveCanvasAspectRatio": "16:9",
  "CanvasFillMode": "color",
  "CanvasPadColor": "black",
  "OutputFormat": "keep_original",
  "Suffix": "_aspectfix",
  "JpegQuality": 95,
  "WebpQuality": 95,
  "Interpolation": "lanczos",
  "Overwrite": false,
  "DeleteSource": false
}
```


保存仕様
--------
処理順は次のとおりです。
1. 元画像を読み込む
2. `XScale / YScale` で内容補正する
3. 必要ならキャンバス処理する
4. 保存する


ログとレポート
--------------
ログ:
- `OutputFolder\logs\aspectfix_YYYYMMDD_HHMMSS.log`
- GUI のログ欄にも同内容を表示します。
- 追加された画像数
- 処理開始時刻
- 各画像の処理結果
- 元サイズ
- 内容補正後サイズ
- 出力サイズ
- 横倍率
- 縦倍率
- 保存キャンバス処理
- エラー内容
- 成功数
- 失敗数

レポート:
- `OutputFolder\aspectfix_report_YYYYMMDD_HHMMSS.txt`
- 内容はすべて日本語です。


補足
----
- 処理対象は GUI リストに入っている画像のみです。
- 同名があれば `_001`, `_002` のように連番回避します。
- 1 枚で失敗しても次の画像へ進みます。
- フォルダ追加は補助機能で、主処理はリスト駆動です。
