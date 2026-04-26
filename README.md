# batch-image-cropper

Windows 11 向けの、画像一括トリミング用 Python スクリプトです。

指定フォルダ内の画像を対象に、左側を一定割合だけ切り捨てて、右側の人物を残す用途を想定しています。
元画像は上書きせず、必ず別フォルダへ出力します。

## 対応内容

- 固定トリミングモード
- 画像のリサイズなし
- EXIF の向き情報を考慮して見た目どおりに処理
- 可能な範囲で EXIF 情報と ICC プロファイルを引き継ぎ
- JPEG 出力時は高品質保存

## 必要環境

- Windows 11
- Python 3.10 以上
- Pillow

インストール例:

```powershell
python -m pip install Pillow
```

## ファイル

- `crop_right_talent.py`

## 使い方

基本:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output"
```

左側を 45% 捨てる例:

```powershell
python crop_right_talent.py --input "C:\photos\input" --output "C:\photos\output" --left-ratio 0.45
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
- `--overwrite`
  - 出力先に同名ファイルが既にある場合に上書きする

## 動作仕様

- 入力フォルダと出力フォルダに同じパスは指定できません。
- 対象拡張子は `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp` です。
- 入力フォルダ直下の画像を処理します。
- EXIF の向き補正後の見た目の横幅を基準に、左から `width * left_ratio` ピクセル分を切り捨てます。
- 残りの右側だけを保存します。
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
