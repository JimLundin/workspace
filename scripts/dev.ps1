param(
    [ValidateSet('check', 'deploy', 'lint', 'typecheck', 'mutate')]
    [string]$Command = 'check',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Create the Windows .venv before running development commands.' }
$env:WORKSPACE_BUNDLED_RUNTIME = Join-Path $env:USERPROFILE 'Downloads\workspace-sdk\workspace\.runtime'
$env:PATH = "C:\Program Files\Git\cmd;$env:PATH"
Push-Location $root
try {
    switch ($Command) {
        'check' { & $python -m scripts.check --native @Arguments }
        'deploy' { & $python -m scripts.deploy deploy @Arguments }
        'mutate' { & $python -m scripts.mutate @Arguments }
        'lint' { & $python -m ruff check @Arguments }
        'typecheck' { & $python -m pyright --pythonpath $python @Arguments }
    }
    exit $LASTEXITCODE
} finally { Pop-Location }
