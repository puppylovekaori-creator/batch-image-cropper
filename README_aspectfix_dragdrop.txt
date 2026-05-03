画像アスペクト補正 GUI
======================

概要
----
Windows 11 向けの、画像の見た目比率を手動倍率で補正し、指定アスペクト比の出力画像をまとめて作る GUI アプリです。
主操作は「複数画像をドラッグ＆ドロップして処理対象リストへ追加する」流れです。
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
4. 処理対象リストへ追加された画像を確認します。
5. `プレビュー更新` で別ウィンドウの補正前 / 補正後プレビューを確認します。
6. `処理開始` を押してリスト内画像だけを一括処理します。

主機能:
- 画像を複数選択してドラッグ＆ドロップ
- リストへ複数画像を追加
- 補正前 / 補正後プレビュー確認
- `処理開始` でリスト内画像を一括処理

補助機能:
- `ファイル追加` でダイアログから複数画像を追加
- `フォルダから追加` でフォルダ内画像を処理対象リストへ追加
- フォルダ追加は主機能ではなく補助機能です


初回セットアップ
----------------
Python 3 が入っていない場合は先にインストールしてください。

推奨コマンド:
py -3 -m pip install -r requirements_aspectfix.txt

`tkinterdnd2` が入っていればドラッグ＆ドロップが有効になります。
入っていなくても、`ファイル追加` ボタンから複数画像を追加して利用できます。


起動
----
- 推奨: `run_aspectfix_dragdrop.bat`
- 直接起動: `py -3 aspectfix_dragdrop_gui.py`

GUI 生成だけ確認したい場合:
py -3 aspectfix_dragdrop_gui.py --headless-smoke-test


GUI項目
-------
大きなドラッグ＆ドロップ領域:
- 表示文言は `ここに画像ファイルをドラッグ＆ドロップ` です。
- 画像ファイルとフォルダのドロップに対応します。

処理対象リスト:
- ファイル名
- 元サイズ
- 現在アスペクト比
- 状態
- 出力予定名

ファイル追加:
- `ファイル追加` で複数画像を追加できます。

フォルダから追加:
- `フォルダから追加` でフォルダ内画像をリストへ追加できます。
- `RecursiveFolderDrop=true` ならサブフォルダも再帰追加します。

リスト操作:
- `選択行を削除`
- `リストをクリア`
- `存在しないファイルを除外`

プレビュー:
- `前の画像` / `次の画像`
- `プレビュー更新`
- `補正前プレビュー` を別ウィンドウで表示
- `補正後プレビュー` を別ウィンドウで表示

情報表示:
- ファイル名
- 元サイズ
- 元アスペクト比
- 補正後サイズ
- 補正後アスペクト比


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
  "XScale": 0.95,
  "YScale": 1.0,
  "TargetAspectRatio": "16:9",
  "OutputCanvasMode": "blur_background",
  "OutputFormat": "keep_original",
  "Suffix": "_aspectfix",
  "JpegQuality": 95,
  "WebpQuality": 95,
  "Interpolation": "lanczos",
  "Overwrite": false,
  "DeleteSource": false
}
```

主な意味:
- `OutputFolder`: 出力先フォルダ
- `RecursiveFolderDrop`: フォルダ追加時に再帰走査するか
- `KeepFolderStructureWhenFolderAdded`: フォルダ追加時に相対フォルダ構造を出力へ残すか
- `XScale` / `YScale`: 横倍率 / 縦倍率
- `TargetAspectRatio`: 例 `16:9`
- `OutputCanvasMode`: 既定は `blur_background`
- `OutputFormat`: `keep_original`, `jpeg`, `png`, `webp`
- `Suffix`: 元ファイル名に付ける接尾辞


処理仕様
--------
- 処理対象は GUI リストに入っている画像のみです。
- 元画像は絶対に上書きしません。
- 出力先は `OutputFolder` です。
- 元ファイル名に `Suffix` を付けて保存します。
- 同名があれば `_001`, `_002` のように連番回避します。
- 1 枚で失敗しても次の画像へ進みます。
- 処理後、リスト上の状態を `完了` / `失敗` / `スキップ` など日本語で更新します。


ログとレポート
--------------
ログ:
- `OutputFolder\logs\aspectfix_YYYYMMDD_HHMMSS.log`
- GUI のログ欄にも同内容を表示します。
- 追加された画像数
- 処理開始時刻
- 各画像の処理結果
- 元サイズ
- 出力サイズ
- 横倍率
- 縦倍率
- 出力方式
- エラー内容
- 成功数
- 失敗数

レポート:
- `OutputFolder\aspectfix_report_YYYYMMDD_HHMMSS.txt`
- 内容はすべて日本語です。


補足
----
- `tkinterdnd2` が利用できない場合でも、`ファイル追加` ボタンから複数追加できます。
- ドロップされたパスに空白や日本語が含まれていても処理できるようにしています。
- フォルダをドロップした場合も、設定に従ってフォルダ内画像を追加します。
