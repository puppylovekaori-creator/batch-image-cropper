# batch-image-cropper aspectfix

画像内容そのものの横伸び・縦伸びを補正して保存する Windows GUI ツールです。主目的は人物比率の歪み補正で、16:9 化やぼかし背景は保存時の仕上げ処理です。

## 基本操作

1. `run_aspectfix_dragdrop.bat` をダブルクリックして起動します。
2. 画像ファイルを複数選択してドラッグ＆ドロップします。
3. `内容の歪み補正` で横倍率 / 縦倍率を調整します。
4. 必要なら `保存時のキャンバス処理` を追加します。
5. `プレビュー更新` で別ウィンドウの補正前 / 補正後を確認します。
6. `処理開始` でリスト内画像を一括処理します。

## 重要

- 横伸び・縦伸びを直すには `内容の歪み補正` の横倍率 / 縦倍率を使います。
- `16:9キャンバスに配置` は、見た目の枠を整えるだけで、人物比率の補正ではありません。
- 処理順は `元画像読込 -> 内容補正 -> 必要ならキャンバス処理 -> 保存` です。

## セットアップ

```powershell
py -3 -m pip install -r requirements_aspectfix.txt
```

## 起動

- 推奨: `run_aspectfix_dragdrop.bat`
- 直接起動: `py -3 aspectfix_dragdrop_gui.py`
- GUI生成確認: `py -3 aspectfix_dragdrop_gui.py --headless-smoke-test`

## 初期値

- 内容補正プリセット: `横を縮める 95%`
- 横倍率: `0.95`
- 縦倍率: `1.0`
- 保存時のキャンバス処理: `内容サイズのまま保存`

## 設定ファイル

`aspectfix_dragdrop_config.json` の既定値:

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

## プレビュー

- 左: 補正前
- 右: 内容補正後
- キャンバス処理が無効なら `内容補正のみ`
- キャンバス処理が有効なら `内容補正 + キャンバス処理`
- 右側は別ウィンドウ表示です

## ログとレポート

- ログ: `OutputFolder/logs/aspectfix_YYYYMMDD_HHMMSS.log`
- レポート: `OutputFolder/aspectfix_report_YYYYMMDD_HHMMSS.txt`
- GUI 文言、ログ、レポート、状態名は日本語です。
