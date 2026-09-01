[CmdletBinding()]
param(
    [switch]$CpuOnly,
    [switch]$SkipModel,
    [switch]$CheckOnly
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$EnvironmentName = 'industry_agent'
. (Join-Path $PSScriptRoot 'windows_helpers.ps1')

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Program,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

Write-Host 'Industry-Academia Agent - Windows setup'
Write-Host "Project: $ProjectRoot"
Write-Host ''

$Conda = Get-CondaExecutable
if (-not $Conda) {
    if ($CheckOnly) {
        throw 'Miniconda, Anaconda, or Miniforge was not found.'
    }

    Write-Host 'A Conda installation was not found.' -ForegroundColor Yellow
    $answer = Read-Host 'Download and silently install official Miniconda for the current user? [Y/n]'
    if ($answer -and $answer -notmatch '^[Yy]') {
        throw 'Setup stopped because Conda is required.'
    }

    $installerUrl = 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe'
    $installerPath = Join-Path ([System.IO.Path]::GetTempPath()) 'industry-agent-miniconda.exe'
    $installRoot = Join-Path $env:USERPROFILE 'miniconda3'
    Write-Host "Downloading official Miniconda from $installerUrl"
    Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $installerPath
    try {
        $installArguments = @(
            '/InstallationType=JustMe',
            '/RegisterPython=0',
            '/AddToPath=0',
            '/S',
            "/D=$installRoot"
        )
        $installer = Start-Process -FilePath $installerPath -ArgumentList $installArguments -Wait -PassThru
        if ($installer.ExitCode -ne 0) {
            throw "Miniconda installer failed with exit code $($installer.ExitCode)."
        }
    }
    finally {
        if (Test-Path -LiteralPath $installerPath) {
            [System.IO.File]::Delete($installerPath)
        }
    }
    $Conda = Join-Path $installRoot 'Scripts\conda.exe'
}

Write-Host "Conda: $Conda"
if ($CheckOnly) {
    $environmentReady = $false
    $null = & $Conda run -n $EnvironmentName python -c 'import chromadb, streamlit, torch' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $environmentReady = $true
    }
    Write-Host "Environment ready: $environmentReady"
    exit $(if ($environmentReady) { 0 } else { 1 })
}

$null = & $Conda run -n $EnvironmentName python --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating Conda environment '$EnvironmentName' with Python 3.11..."
    Invoke-Checked -Program $Conda -Arguments @(
        'create', '-n', $EnvironmentName, 'python=3.11', 'pip', '-y'
    ) -FailureMessage 'Could not create the Conda environment.'
}
else {
    Write-Host "Using existing Conda environment '$EnvironmentName'."
}

Push-Location $ProjectRoot
try {
    Invoke-Checked -Program $Conda -Arguments @(
        'run', '-n', $EnvironmentName, 'python', '-m', 'pip',
        'install', '--upgrade', 'pip'
    ) -FailureMessage 'Could not update pip.'

    $useGpu = (-not $CpuOnly) -and ($null -ne (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue))
    $platformRequirements = if ($useGpu) {
        'requirements-gpu-windows.txt'
    }
    else {
        'requirements-cpu.txt'
    }
    Write-Host "Installing dependencies with $platformRequirements..."
    Invoke-Checked -Program $Conda -Arguments @(
        'run', '-n', $EnvironmentName, 'python', '-m', 'pip', 'install',
        '-r', 'requirements.txt', '-r', $platformRequirements
    ) -FailureMessage 'Could not install project dependencies.'

    foreach ($directory in @(
        'data\raw\papers',
        'data\processed\capabilities',
        'data\processed\teacher_profiles'
    )) {
        $null = New-Item -ItemType Directory -Path (Join-Path $ProjectRoot $directory) -Force
    }

    $envPath = Join-Path $ProjectRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot '.env.example') -Destination $envPath
        Write-Host 'Created .env from .env.example. Add a Moonshot key only if you use paper Q&A.'
    }

    Invoke-Checked -Program $Conda -Arguments @(
        'run', '-n', $EnvironmentName, 'python', '-c',
        'import chromadb, pymupdf, sentence_transformers, streamlit, torch; print("Dependency check passed; torch=" + torch.__version__ + "; cuda=" + str(torch.cuda.is_available()))'
    ) -FailureMessage 'Dependency import check failed.'

    if (-not $SkipModel) {
        Write-Host 'Downloading or validating the local BGE embedding model...'
        Invoke-Checked -Program $Conda -Arguments @(
            'run', '-n', $EnvironmentName, 'python', '-c',
            'from src.retrieval.embedder import LocalEmbedder; model=LocalEmbedder(); print("BGE ready on " + model.device)'
        ) -FailureMessage 'Could not prepare the local BGE model.'
    }
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Setup completed successfully.' -ForegroundColor Green
Write-Host 'Next: install synthetic sample data or add your own papers, then run Start-Web-Demo.cmd.'
