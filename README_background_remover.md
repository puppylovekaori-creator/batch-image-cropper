# 背景削除一括処理 GUI

`background_remover_gui.py` は、`rembg` を使って大量のフレーム画像から背景を削除し、人物だけを残した PNG を一括生成する Windows 向け Tkinter GUI ツールです。

## ファイル

- `background_remover_gui.py`
- `Open-BackgroundRemoverGui.cmd`
- `run_background_remover_gui.bat`
- `Setup-BackgroundRemoverGui.cmd`
- `Setup-BackgroundRemoverGui.ps1`
- `background_remover_gui_settings.json`

## 対応内容

- 入力フォルダ / 出力フォルダの GUI 選択
- `jpg / jpeg / png / webp / bmp` の選択処理
- サブフォルダ再帰処理
- 入力フォルダ配下の相対パス維持
- 出力済みファイルのスキップ
- `透過PNG / 白背景PNG / 黒背景PNG / グリーン背景PNG / マスク画像のみ`
- 元ファイル名維持または suffix 付与
- `rembg` モデル選択
- Alpha matting
- 処理前の長辺リサイズ
- 簡易人物スコアのファイル名先頭付与
- 低スコア画像の出力除外
- 進捗表示
- GUI ログ表示
- 出力フォルダへの `background_removal_log.txt` 保存
- 中断
- 設定 JSON の保存 / 復元
- プレビュー

## 必要環境

- Windows 10 / 11
- Python 3.11 - 3.13
- Pillow
- rembg

2026-04-30 時点で、`rembg` の公式 README は Python 要件を `>=3.11, <3.14` としています。  
このPCの既定 `python` が 3.14 の場合は、そのままだと `rembg` を使えない可能性があります。

公式:

- [rembg README](https://github.com/danielgatis/rembg)
- [rembg USAGE.md](https://github.com/danielgatis/rembg/blob/main/USAGE.md)

## インストール

CPU 版:

```powershell
pip install "rembg[cpu]" pillow
```

CLI も使う場合:

```powershell
pip install "rembg[cpu,cli]" pillow
```

Python 3.14 が既定の環境では、Python 3.11 - 3.13 を別途入れてから、そのバージョンに対してインストールしてください。

例:

```powershell
py -3.13 -m pip install "rembg[cpu]" pillow
```

ダブルクリックでまとめて入れたい場合:

- `Setup-BackgroundRemoverGui.cmd`

このセットアップは次をまとめて実行します。

1. `Python 3.13` が無ければ `winget` で導入
2. `pip` 更新
3. `rembg[cpu]` と `pillow` の導入
4. `import rembg, PIL` の確認

## 起動

最も簡単:

```powershell
Open-BackgroundRemoverGui.cmd
```

これはダブルクリック起動用です。可能なら `pyw -3.13` を優先して使い、コンソールを出さずに GUI を開きます。

従来のバッチ起動:

```powershell
.\run_background_remover_gui.bat
```

Python から直接起動:

```powershell
python .\background_remover_gui.py
```

`run_background_remover_gui.bat` は `py -3.13 / 3.12 / 3.11` を順に探し、見つからなければ `python` で起動します。

## 初回実行

- 初回は `rembg` モデルのダウンロードで時間がかかる場合があります。
- 初回モデル取得時はインターネット接続が必要になる場合があります。
- モデルファイルは初回利用時に自動ダウンロードされる場合があります。

## 推奨モデル

人物フレーム処理:

- `u2net_human_seg`

汎用:

- `isnet-general-use`
- `birefnet-general`

高速軽量:

- `u2netp`
- `silueta`

## 推奨運用

1. `ffmpeg` で動画からフレーム抽出
2. このツールで背景削除
3. `透過PNG` または `白背景PNG` を作成
4. 目視で本人性が強い画像だけを選ぶ
5. 参照セット用フォルダへ分類する

## 簡易人物スコアについて

- `rembg` 自体が人物認識の信頼度スコアを返すわけではありません。
- このツールの `簡易人物スコア` は、背景削除後のアルファマスクの面積やまとまり方から作る近似値です。
- 範囲は `0 - 1000` です。
- `score` が高いほど「前景としてまとまって残っている」画像を上位にしやすくなります。
- ただし、これは人物そのものの真の認識確率ではありません。
- フレームの選別補助として使う前提です。

`ファイル名の先頭に score を付ける` を有効にすると、例として次のような名前になります。

```text
s0873_frame_000001_nobg.png
```

高スコア順で見たい場合は、エクスプローラーで名前を降順ソートしてください。

`score がしきい値未満なら出力しない` を有効にすると、低スコア画像は出力を作りません。  
同じ出力先に既存ファイルがある場合は、その既存出力も削除対象になります。  
入力元画像は削除しません。

## 使い方

1. 入力フォルダと出力フォルダを指定します。
2. 対象拡張子、再帰処理、サブフォルダ維持、スキップ設定を選びます。
3. 出力形式、ファイル名モード、`rembg` モデルを選びます。
4. 必要なら Alpha matting や前処理リサイズを有効にします。
5. 必要なら `簡易人物スコア` の prefix / 低スコア除外を有効にします。
6. `対象ファイル数を確認` で件数を確認します。
7. 必要なら `プレビュー` で設定を試します。
8. `開始` を押します。
9. 中断したい場合は `中断` を押します。

## ログ

処理完了後、出力フォルダに次のログを保存します。

```text
background_removal_log.txt
```

記録内容:

- 実行日時
- 入力フォルダ
- 出力フォルダ
- モデル
- 出力形式
- 処理対象数
- 成功数
- スキップ数
- 低スコア除外数
- エラー数
- エラー一覧

## 設定ファイル

設定はスクリプトと同じフォルダに保存されます。

```text
background_remover_gui_settings.json
```

起動時に自動読込し、`設定保存` / `設定読込` でも操作できます。
