param(
    [ValidateSet('setup', 'check', 'deploy', 'lint', 'format', 'typecheck', 'watch', 'preview', 'volume')]
    [string]$Command = 'check',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if ($Command -eq 'setup') {
    # The development environment holds exactly the pinned lock, like an installed one, plus the dev-only tools.
    if (-not (Test-Path $python)) { & py -3.15 -m venv (Join-Path $root '.venv'); if ($LASTEXITCODE) { exit $LASTEXITCODE } }
    Remove-Item (Join-Path $root '.venv\Lib\site-packages\workspace_runtime.pth') -ErrorAction SilentlyContinue
    & $python -m pip install --disable-pip-version-check --no-deps --require-hashes --only-binary=:all: -r (Join-Path $root 'requirements\windows-py315.lock')
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $python -m pip install --disable-pip-version-check hypothesis 'watchdog==6.0.0'
    exit $LASTEXITCODE
}
if (-not (Test-Path $python)) { throw 'Run Dev.cmd setup first: it creates the development .venv from the lock.' }
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
        'volume' { & $python -B -m scripts.volume @Arguments }
        'typecheck' { & $python -m scripts.typecheck --pythonpath $python @Arguments }
    }
    exit $LASTEXITCODE
} finally { Pop-Location }
