# batch-image-cropper

画像アスペクト補正用の Windows GUI ツールです。主操作は「画像を複数選択してドラッグ＆ドロップし、プレビューを確認してから一括処理する」流れです。元画像は上書きせず、必ず `OutputFolder` 配下へ別名保存します。

## 基本操作

1. `run.bat` をダブルクリックして起動します。
2. エクスプローラーで画像ファイルを複数選択します。
3. GUI のドロップ領域へドラッグ＆ドロップします。
4. 処理対象リストを確認し、`プレビュー更新` で補正前 / 補正後を確認します。
5. `処理開始` を押してリスト内画像だけを一括処理します。

補助機能として `ファイル追加` と `フォルダから追加` もあります。フォルダ追加はリスト投入用であり、主機能ではありません。

## セットアップ

```powershell
py -3 -m pip install -r requirements.txt
```

`tkinterdnd2` が入っていれば D&D が有効になります。未導入でも `ファイル追加` ボタンから複数画像を追加できます。

## 起動

- 推奨: `run.bat`
- 直接起動: `py -3 main.py`
- GUI生成確認: `py -3 main.py --headless-smoke-test`

## 設定

`config.json` の既定値:

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

## 処理仕様

- 処理対象は GUI リスト内の画像のみです。
- 出力先は `OutputFolder` です。
- 元ファイル名に `Suffix` を付けて保存します。
- 同名があれば `_001`, `_002` のように連番回避します。
- 1枚で失敗しても次の画像へ進みます。
- フォルダ追加は補助機能で、主処理はリスト駆動です。

## ログとレポート

- ログ: `OutputFolder/logs/aspectfix_YYYYMMDD_HHMMSS.log`
- レポート: `OutputFolder/aspectfix_report_YYYYMMDD_HHMMSS.txt`
- GUI文言、ログ、レポート、状態名は日本語です。
