param(
    [ValidateSet('check', 'deploy', 'lint', 'format', 'typecheck', 'watch', 'preview')]
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
        'check' { & $python -m scripts.check --standards @Arguments }
        'watch' { & $python -B -m scripts.watch @Arguments }
        'preview' { & $python -B -m scripts.watch --preview-only --preview @Arguments }
        'deploy' { & $python -m scripts.deploy @Arguments }
        'lint' { & $python -m ruff check @Arguments }
        'format' { & $python -m ruff format @Arguments }
        'typecheck' { & $python -m scripts.typecheck --pythonpath $python @Arguments }
    }
    exit $LASTEXITCODE
} finally { Pop-Location }
