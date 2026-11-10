# Merchant Knowledge Base launcher for Windows PowerShell 5.1+ and PowerShell 7.
# This file is intentionally ASCII-only so that it runs under any console code page.
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'start', 'stop', 'samples', 'check', 'verify', 'test', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$EnvFile = Join-Path $Root '.env'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$Npm = 'npm'
if ($env:OS -eq 'Windows_NT') { $Npm = 'npm.cmd' }
Add-Type -AssemblyName System.Net.Http

function Show-Usage {
    Write-Host 'Usage: scripts\zhiku.ps1 <command>'
    Write-Host ''
    Write-Host '  setup    First-time install: create .env, start services, install dependencies'
    Write-Host '           and build the frontend'
    Write-Host '  start    Start services and the backend (foreground, Ctrl+C stops the backend)'
    Write-Host '  stop     Stop services (all data is kept)'
    Write-Host '  samples  Import the three sample manuals from the samples folder (backend must be running)'
    Write-Host '  check    Check that every dependency is ready'
    Write-Host '  verify   End-to-end acceptance: import the samples and ask real questions (backend must be running)'
    Write-Host '  test     Run backend and frontend unit tests'
}

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command '$Name'. $Hint"
    }
}

# Reads a value from .env; returns the default when it is missing or empty.
function Get-EnvValue([string]$Name, [string]$Default) {
    if (Test-Path -LiteralPath $EnvFile) {
        $line = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
            Where-Object { $_.StartsWith($Name + '=') } |
            Select-Object -Last 1
        if ($line) {
            $value = $line.Substring($Name.Length + 1).Trim()
            if ($value) { return $value }
        }
    }
    return $Default
}

function New-Secret {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLower()
}

function Initialize-EnvFile {
    if (Test-Path -LiteralPath $EnvFile) { return }
    $secretNames = @('MONGO_PASSWORD')
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($line in (Get-Content -LiteralPath (Join-Path $Root '.env.example') -Encoding UTF8)) {
        $name = ($line -split '=', 2)[0]
        if ($secretNames -contains $name) {
            $lines.Add($name + '=' + (New-Secret))
        } else {
            $lines.Add($line)
        }
    }
    # UTF-8 without BOM: Docker Compose and python-dotenv both read it correctly.
    [IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Created .env with a random database password.'
}

function Assert-EnvFile {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw 'No .env yet. Run first: scripts\zhiku.ps1 setup'
    }
}

# Runs a native command in a directory and fails loudly on a non-zero exit code.
function Invoke-Native([string]$WorkingDirectory, [string]$File, [string[]]$Arguments) {
    Push-Location $WorkingDirectory
    try {
        & $File @Arguments | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "'$File $($Arguments -join ' ')' failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

# Local services are probed without the system proxy.
function Test-Http([string]$Url) {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(4)
    try {
        return $client.GetAsync($Url).GetAwaiter().GetResult().IsSuccessStatusCode
    } catch {
        return $false
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Wait-Http([string]$Name, [string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $announced = $false
    while (-not (Test-Http $Url)) {
        if ((Get-Date) -ge $deadline) {
            throw "$Name was not ready within $TimeoutSeconds seconds. See: docker compose logs"
        }
        if (-not $announced) {
            Write-Host "Waiting for $Name ..."
            $announced = $true
        }
        Start-Sleep -Seconds 3
    }
}

function Start-Services {
    Assert-Command 'docker' 'Install and start Docker Desktop first.'
    Invoke-Native $Root 'docker' @('compose', 'up', '-d', '--wait')
    # The first start downloads about 2.4 GB of model weights and warms both models up on CPU.
    Wait-Http 'the embedding model (the first start downloads the model and can take 10+ minutes)' `
        ('http://127.0.0.1:' + (Get-EnvValue 'EMBEDDING_PORT' '18181') + '/health') 1800
    Wait-Http 'the reranker model' ('http://127.0.0.1:' + (Get-EnvValue 'RERANK_PORT' '18182') + '/health') 1800
}

try {
    switch ($Command) {
        'setup' {
            Assert-Command 'docker' 'Install and start Docker Desktop first.'
            Assert-Command 'uv' 'See https://docs.astral.sh/uv/ for installation.'
            Assert-Command $Npm 'Install Node.js 20 or newer first.'
            Initialize-EnvFile
            Start-Services
            Invoke-Native $Backend 'uv' @('sync', '--locked')
            Invoke-Native $Frontend $Npm @('ci')
            Invoke-Native $Frontend $Npm @('run', 'build')
            Invoke-Native $Backend 'uv' @('run', 'python', '-m', 'app.scripts.check_environment')
            Write-Host ''
            Write-Host 'Setup finished.'
            if (-not (Get-EnvValue 'LLM_API_KEY' '')) {
                Write-Host 'Next: put your LLM_API_KEY into .env, then run: scripts\zhiku.ps1 start'
            } else {
                Write-Host 'Next: run scripts\zhiku.ps1 start'
            }
        }
        'start' {
            Assert-EnvFile
            Assert-Command 'uv' 'See https://docs.astral.sh/uv/ for installation.'
            Start-Services
            if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $Frontend 'dist') 'index.html'))) {
                Write-Host 'Note: the frontend is not built yet (cd frontend; npm ci; npm run build). Only the API is served.'
            }
            Write-Host ('Open http://127.0.0.1:' + (Get-EnvValue 'APP_PORT' '18100'))
            Invoke-Native $Backend 'uv' @('run', 'python', 'main.py')
        }
        'stop' {
            Assert-EnvFile
            Invoke-Native $Root 'docker' @('compose', 'stop')
            Write-Host 'Services stopped. Data volumes are kept.'
        }
        'samples' {
            Assert-EnvFile
            Invoke-Native $Backend 'uv' @('run', 'python', '-m', 'app.scripts.import_samples')
        }
        'check' {
            Assert-EnvFile
            Invoke-Native $Root 'docker' @('compose', 'ps')
            Invoke-Native $Backend 'uv' @('run', 'python', '-m', 'app.scripts.check_environment')
        }
        'verify' {
            Assert-EnvFile
            Invoke-Native $Backend 'uv' @('run', 'python', '-m', 'app.scripts.verify_live')
        }
        'test' {
            Invoke-Native $Backend 'uv' @('run', 'python', '-m', 'pytest', '-q')
            Invoke-Native $Frontend $Npm @('test')
        }
        default {
            Show-Usage
        }
    }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
