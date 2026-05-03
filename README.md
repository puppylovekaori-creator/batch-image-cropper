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

## ffmpeg フレーム抽出 GUI

`New-FfmpegFrameExtractCommandGui.pyw` は、動画から静止画フレームを抜くための GUI です。
従来どおり 1 本だけの単体モードも使えますが、現在は複数動画をキューへ積んで夜間バッチ処理できる構成になっています。

- ダブルクリック起動:
  - `Open-New-FfmpegFrameExtractCommandGui.cmd`
- Python から直接起動:

```powershell
py -3 .\New-FfmpegFrameExtractCommandGui.pyw
```

### 主な機能

- 単一動画モード
  - 従来どおり PowerShell 用の `ffmpeg` コマンド生成と単発実行ができます。
- 複数動画バッチモード
  - 複数動画キュー
  - フォルダ一括追加
  - ドラッグ＆ドロップ追加
  - 順次フレーム抽出
  - 失敗時も次動画へ継続
  - 一時停止 / 再開 / キャンセル
- 出力先制御
  - 出力ルートフォルダ指定
  - `{動画名}_frames` 自動サブフォルダ
  - 重複時の既存フォルダ利用 or 連番フォルダ
  - 既存出力のスキップ / 連番退避 / 作り直し
- 抽出設定
  - `10秒ごと / 5秒ごと / 1秒ごと / 指定秒ごと / 全フレーム`
  - `jpg / png`
  - JPG 品質
  - 開始位置 / 終了位置 / 抽出時間(旧互換)
  - リサイズ
  - ファイル名パターン
- 運用補助
  - ドライラン
  - 実行ログ
  - summary TXT / JSON
  - ジョブ保存 / 読込
  - 実行中のスリープ抑止
  - 完了後アクション

### 単一動画モードの使い方

1. `入力動画ファイル` を指定します。
2. `単体出力フォルダ` と `単体連番ベース名` を指定します。
3. 必要に応じて `抽出方式 / JPG 品質 / 開始位置 / 終了位置 / リサイズ` を調整します。
4. `コマンド生成` で PowerShell 用コマンドを作ります。
5. `コピー` または `生成してコピー` でクリップボードへ送れます。
6. `実行` を押すと、別 PowerShell で実際に `ffmpeg` を起動します。

### 複数動画バッチモードの使い方

1. 上段の `入力動画キュー` に動画を追加します。
2. `出力ルートフォルダ` を指定します。
3. 必要なら `出力ファイル名パターン` を変更します。
   - 既定値: `{video_name}_{frame_no}`
   - 例: `{video_name}_{timestamp}_{frame_no}`
4. `サブフォルダ重複時` と `既存出力の扱い` を確認します。
5. `ドライラン` で予定を確認します。
6. 問題なければ `一括実行` を押します。
7. `一時停止` は現在動画の完了後に停止します。
8. `再開` は未処理だけを続きから処理します。
9. `キャンセル` は現在の `ffmpeg` を止め、残りをキャンセル扱いにします。

### ドライランの使い方

ドライランでは実際の抽出は行いません。以下をログ欄へ出します。

- 対象動画数
- 各動画の長さ
- 各動画の推定出力枚数
- 全体の推定出力枚数
- 出力予定フォルダ
- 既存フォルダ衝突時の扱い
- 既存出力がある場合の挙動
- `ffmpeg` / `ffprobe` の確認結果

### ジョブ保存 / 読込

- `ジョブ保存`
  - 現在のキューと設定を JSON へ保存します。
- `ジョブ読込`
  - 以前保存した JSON を読み込み、キューと設定を復元します。

保存される主な内容:

- 出力ルート
- 抽出間隔
- 開始位置 / 終了位置
- 出力形式
- JPG 品質
- リサイズ設定
- ファイル名パターン
- 既存出力の扱い
- スリープ抑止
- 完了後アクション
- `ffmpeg` パス設定
- 動画キュー

### スリープ抑止について

`実行中は PC スリープを抑止する` を ON にすると、バッチ実行中だけ Windows のスリープ抑止を試みます。
処理終了・一時停止・キャンセル時には解除します。

### 完了後アクションの注意

- 初期値は `何もしない` です。
- `PC をシャットダウン` と `PC をスリープ` は実行前に確認ダイアログを出します。
- 夜間運用で使う前に、短いテスト動画で動作確認してから本番投入してください。

### 既存出力の扱い

- `既存出力があればスキップ`
  - 既に出力済みのフォルダがあれば、その動画は処理しません。
- `既存出力があれば連番フォルダを作る`
  - 既存結果を残したまま、新しい `_001`, `_002` フォルダへ出します。
- `既存出力を消して作り直す`
  - 明示的に選んだ場合だけ削除確認を出し、その後に再作成します。

### ログと summary

- 実行ログ
  - `logs/ffmpeg_batch_extract_YYYYMMDD_HHMMSS.log`
- summary TXT
  - `出力ルート\batch_extract_summary_YYYYMMDD_HHMMSS.txt`
- summary JSON
  - `出力ルート\batch_extract_summary_YYYYMMDD_HHMMSS.json`

summary には、開始終了時刻、各動画の状態、出力先、推定枚数、実出力枚数、`ffmpeg` コマンド、終了コード、エラー内容が入ります。

### 夜間バッチ処理の手順

1. 先に 1 本だけでドライランします。
2. 問題なければ 2 ～ 3 本で短時間テストします。
3. 出力先、ファイル名パターン、既存出力の扱いを確認します。
4. `実行中は PC スリープを抑止する` を ON にします。
5. 完了後アクションが `何もしない` のままか確認します。
6. `一括実行` を押して放置します。
7. 翌朝にログと summary を見て、失敗動画だけ再投入します。

### トラブルシュート

- `ffmpeg が見つからない`
  - `ffmpeg.exe のフルパスを指定する` を ON にして、実ファイルを指定してください。
- `日本語パスで失敗する`
  - まずドライランでパス表示を確認してください。Windows 標準のパス表現で扱う実装です。
- `出力枚数が想定より少ない`
  - `開始位置 / 終了位置 / 抽出時間` と `抽出方式` を見直してください。
  - `全フレーム` 以外は間引き抽出です。
- `途中で失敗した動画がある`
  - 他動画の成功結果は残ります。summary TXT/JSON とログを見て、失敗動画だけ再投入してください。
- `夜間処理中に止まった`
  - `ログ` と `batch_extract_summary_*.json` を確認してください。
  - スリープ抑止を ON にしても、Windows の電源設定や手動スリープまでは防げません。

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
