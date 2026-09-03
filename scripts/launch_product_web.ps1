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

$AppPath = Join-Path $ProjectRoot 'app\web_api.py'
if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
    Write-Host '[ERROR] app\web_api.py was not found.' -ForegroundColor Red
    exit 1
}

if ($Port -eq 0) {
    $Port = 8000
    if ($env:PRODUCT_DEMO_PORT) {
        $parsedPort = 0
        if (-not [int]::TryParse($env:PRODUCT_DEMO_PORT, [ref]$parsedPort)) {
            Write-Host '[ERROR] PRODUCT_DEMO_PORT must be an integer.' -ForegroundColor Red
            exit 1
        }
        $Port = $parsedPort
    }
}
if ($Port -lt 1 -or $Port -gt 65535) {
    Write-Host '[ERROR] The web port must be between 1 and 65535.' -ForegroundColor Red
    exit 1
}

$env:PYTHONUTF8 = '1'
if (-not $env:INDUSTRY_AGENT_CATALOG_PATH) {
    $env:INDUSTRY_AGENT_CATALOG_PATH = Join-Path $ProjectRoot 'data\metadata\papers.sqlite3'
}
if (-not $env:INDUSTRY_AGENT_PAPER_LIBRARY_DIR) {
    $adjacentPaperLibrary = Join-Path (Split-Path $ProjectRoot -Parent) '论文'
    if (Test-Path -LiteralPath $adjacentPaperLibrary -PathType Container) {
        $env:INDUSTRY_AGENT_PAPER_LIBRARY_DIR = $adjacentPaperLibrary
    }
}

try {
    & $Python -c 'import fastapi, uvicorn' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'missing dependencies'
    }
}
catch {
    Write-Host '[ERROR] FastAPI dependencies are missing.' -ForegroundColor Red
    Write-Host 'Run Setup-Windows.cmd once, then launch this file again.'
    exit 1
}

$Url = "http://127.0.0.1:$Port"
$HealthUrl = "$Url/api/health"

if ($CheckOnly) {
    Write-Host 'Product web launcher check passed.' -ForegroundColor Green
    Write-Host "Python: $Python"
    Write-Host "App: $AppPath"
    Write-Host "URL: $Url"
    exit 0
}

try {
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1
    if ($health.status -eq 'ok') {
        Write-Host "The product web demo is already running at $Url"
        if (-not $NoBrowser) {
            Start-Process $Url
        }
        exit 0
    }
}
catch {
    # No existing server is expected on the first launch.
}

Write-Host 'Starting the product web preview...'
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
                $response = Invoke-RestMethod -Uri "$TargetUrl/api/health" -TimeoutSec 1
                if ($response.status -eq 'ok') {
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
    & $Python -m uvicorn app.web_api:create_app --factory --host 127.0.0.1 --port $Port
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
