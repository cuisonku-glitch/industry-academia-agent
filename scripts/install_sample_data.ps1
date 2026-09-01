[CmdletBinding()]
param()

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

Push-Location $ProjectRoot
try {
    & $Python (Join-Path $PSScriptRoot 'bootstrap_sample_data.py')
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -eq 0) {
    Write-Host ''
    Write-Host 'Synthetic sample data is ready. Run Start-Web-Demo.cmd.' -ForegroundColor Green
}
exit $exitCode
