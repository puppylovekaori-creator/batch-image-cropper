# batch-image-cropper

Windows 11 向けの、画像一括トリミング用 Python スクリプトです。

指定フォルダ内の画像を対象に、左側を一定割合だけ切り捨てて、右側の人物を残す用途を想定しています。
元画像は上書きせず、必ず別フォルダへ出力します。

## 対応内容

- 固定トリミングモード
- 顔位置ベースの境界補正モード
- 画像のリサイズなし
- EXIF の向き情報を考慮して見た目どおりに処理
- 可能な範囲で EXIF 情報と ICC プロファイルを引き継ぎ
- JPEG 出力時は高品質保存

## 必要環境

- Windows 11
- Python 3.10 以上
- Pillow
- 顔位置補正を使う場合は `opencv-python-headless`

インストール例:

```powershell
python -m pip install Pillow
```

顔位置補正モードも使う場合:

```powershell
python -m pip install Pillow opencv-python-headless
```

## ファイル

- `crop_right_talent.py`
- `New-FfmpegFrameExtractCommandGui.pyw`
- `Open-New-FfmpegFrameExtractCommandGui.cmd`

## ffmpeg コマンド GUI

動画から静止画フレームを抜くための `ffmpeg` コマンドを GUI で組み立てるツールです。

- ダブルクリック起動:
  - `Open-New-FfmpegFrameExtractCommandGui.cmd`
- Python から直接起動:

```powershell
py -3 .\New-FfmpegFrameExtractCommandGui.pyw
```

主な機能:

- 入力動画ファイル選択
- 出力フォルダ選択
- `10秒ごと / 5秒ごと / 1秒ごと / 指定秒ごと / 全フレーム`
- `jpg / png` 切替
- `-ss` と `-t` の付与
- PowerShell 用コマンド生成
- クリップボードコピー
- 前回設定の JSON 保存復元

## 使い方

基本:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output"
```

左側を 45% 捨てる例:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output" --left-ratio 0.45
```

右側の人物の顔位置を使って、固定比率より少し右へ境界を寄せたい場合:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output" --mode face-gap --left-ratio 0.45
```

既存の出力ファイルを上書きしたい場合:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output" --overwrite
```

## オプション

- `--input`
  - 元画像フォルダ
- `--output`
  - 切り抜き後の出力先フォルダ
- `--left-ratio`
  - 左側をどれだけ捨てるかの割合
  - 既定値は `0.45`
- `--mode`
  - `fixed`
  - `--left-ratio` だけで固定的に切る既定モード
  - `face-gap`
  - 右側の顔位置を検出し、左人物の残りを減らすように境界を右へ寄せるモード
- `--face-cascade`
  - `face-gap` モードで使う Haar cascade XML の任意指定パス
- `--overwrite`
  - 出力先に同名ファイルが既にある場合に上書きする

## 動作仕様

- 入力フォルダと出力フォルダに同じパスは指定できません。
- 対象拡張子は `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp` です。
- 入力フォルダ直下の画像を処理します。
- EXIF の向き補正後の見た目の横幅を基準に、左から `width * left_ratio` ピクセル分を切り捨てます。
- 残りの右側だけを保存します。
- `face-gap` モードでは、まず `left_ratio` の固定境界を作り、その後で右側顔の検出結果に応じて境界をさらに右へ寄せます。
- 顔がうまく検出できなかった画像は、自動的に固定モード相当へフォールバックします。
- ピクセルの拡大縮小は行いません。
- JPEG は `quality=95`, `subsampling=0` で保存します。

## テスト例

今回のテスト用入力フォルダ:

```text
H:\DropBox\Dropbox\95_Personal\志田こはく
```

テスト用出力フォルダ例:

```text
H:\DropBox\Dropbox\95_Personal\志田こはく_right_crop_test
```
