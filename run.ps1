$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python (Join-Path $ScriptDir "ecnu_calendar.py") @args
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $ScriptDir "ecnu_calendar.py") @args
}
else {
    throw "未找到 Python 3。请检查 Python 是否已加入 PATH。"
}

if ($LASTEXITCODE -ne 0) {
    throw "课表转换失败，退出码：$LASTEXITCODE"
}
