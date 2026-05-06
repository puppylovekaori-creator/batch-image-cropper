param()

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Test-PythonTag {
    param([string]$Tag)
    & py "-$Tag" -c "import sys; print(sys.executable)" *> $null
    return ($LASTEXITCODE -eq 0)
}

Write-Step "Python 3.13 を確認"
$pythonTag = $null
foreach ($candidate in @("3.13", "3.12", "3.11")) {
    if (Test-PythonTag -Tag $candidate) {
        $pythonTag = $candidate
        break
    }
}

if (-not $pythonTag) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.11-3.13 が見つからず、winget も使えません。Python 3.13 を先にインストールしてください。"
    }

    Write-Step "Python 3.13 を winget でインストール"
    & winget install --id Python.Python.3.13 --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget による Python 3.13 インストールに失敗しました。"
    }

    if (-not (Test-PythonTag -Tag "3.13")) {
        throw "Python 3.13 のインストール後も py -3.13 が見つかりません。PowerShell を開き直して再実行してください。"
    }
    $pythonTag = "3.13"
}

Write-Step "pip を更新"
& py "-$pythonTag" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip 更新に失敗しました。"
}

Write-Step "rembg / pillow をインストール"
& py "-$pythonTag" -m pip install "rembg[cpu]" pillow
if ($LASTEXITCODE -ne 0) {
    throw "rembg / pillow のインストールに失敗しました。"
}

Write-Step "動作確認"
& py "-$pythonTag" -c "import rembg, PIL; print('OK', getattr(rembg, '__version__', 'unknown'), PIL.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "インストール後の import 確認に失敗しました。"
}

Write-Step "完了"
Write-Host "使用 Python: $pythonTag"
Write-Host "GUI 起動: Open-BackgroundRemoverGui.cmd をダブルクリック"
