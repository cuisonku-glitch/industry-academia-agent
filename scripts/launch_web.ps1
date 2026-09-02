[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [int]$Port = 0
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'windows_helpers.ps1')

try {
    $Python = Get-ProjectPython -ProjectRoot $ProjectRoot
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$AppPath = Join-Path $ProjectRoot 'app\app.py'
if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
    Write-Host '[ERROR] app\app.py was not found.' -ForegroundColor Red
    exit 1
}

if ($Port -eq 0) {
    $configuredPort = 8501
    if ($env:DEMO_PORT) {
        $parsedPort = 0
        if (-not [int]::TryParse($env:DEMO_PORT, [ref]$parsedPort)) {
            Write-Host '[ERROR] DEMO_PORT must be an integer.' -ForegroundColor Red
            exit 1
        }
        $configuredPort = $parsedPort
    }
    $Port = $configuredPort
}
if ($Port -lt 1 -or $Port -gt 65535) {
    Write-Host '[ERROR] The web port must be between 1 and 65535.' -ForegroundColor Red
    exit 1
}

$Url = "http://127.0.0.1:$Port"
$HealthUrl = "$Url/_stcore/health"
$env:PYTHONUTF8 = '1'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
if (-not $env:INDUSTRY_AGENT_CATALOG_PATH) {
    $env:INDUSTRY_AGENT_CATALOG_PATH = Join-Path $ProjectRoot 'data\metadata\papers.sqlite3'
}
if (-not $env:INDUSTRY_AGENT_PAPER_LIBRARY_DIR) {
    $adjacentPaperLibrary = Join-Path (Split-Path $ProjectRoot -Parent) '论文'
    if (Test-Path -LiteralPath $adjacentPaperLibrary -PathType Container) {
        $env:INDUSTRY_AGENT_PAPER_LIBRARY_DIR = $adjacentPaperLibrary
    }
}

if ($CheckOnly) {
    Write-Host 'Web launcher check passed.' -ForegroundColor Green
    Write-Host "Python: $Python"
    Write-Host "App: $AppPath"
    Write-Host "URL: $Url"
    exit 0
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 1
    if ($health.Content -eq 'ok') {
        Write-Host "The web demo is already running at $Url"
        if (-not $NoBrowser) {
            Start-Process $Url
        }
        exit 0
    }
}
catch {
    # No existing server is expected on the first launch.
}

Write-Host 'Starting the Industry-Academia Agent web demo...'
Write-Host "Python: $Python"
Write-Host "URL: $Url"
Write-Host 'Keep this window open. Press Ctrl+C to stop the server.'
Write-Host ''

$browserJob = $null
if (-not $NoBrowser) {
    $browserJob = Start-Job -ScriptBlock {
        param($TargetUrl)
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri "$TargetUrl/_stcore/health" -TimeoutSec 1
                if ($response.Content -eq 'ok') {
                    Start-Process $TargetUrl
                    return
                }
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } -ArgumentList $Url
}

Push-Location $ProjectRoot
try {
    & $Python -m streamlit run $AppPath --server.address 127.0.0.1 --server.port $Port
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    if ($browserJob) {
        Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}

exit $exitCode
