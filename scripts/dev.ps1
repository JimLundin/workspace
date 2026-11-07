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
    # The development environment holds exactly uv.lock, like an installed one, plus the dev group.
    # uv, as installs use: --native-tls trusts the Windows certificate store (company TLS inspection).
    Remove-Item (Join-Path $root '.venv\Lib\site-packages\workspace_runtime.pth') -ErrorAction SilentlyContinue
    & uv sync --native-tls --locked --no-install-project --python 3.15 --project $root
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
