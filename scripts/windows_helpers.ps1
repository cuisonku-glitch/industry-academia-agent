Set-StrictMode -Version 2.0

function Get-CondaExecutable {
    $candidates = @()

    if ($env:CONDA_EXE) {
        $candidates += $env:CONDA_EXE
    }

    foreach ($root in @(
        (Join-Path $env:USERPROFILE 'miniconda3'),
        (Join-Path $env:USERPROFILE 'anaconda3'),
        (Join-Path $env:USERPROFILE 'miniforge3'),
        (Join-Path $env:LOCALAPPDATA 'miniconda3'),
        (Join-Path $env:LOCALAPPDATA 'anaconda3'),
        (Join-Path $env:LOCALAPPDATA 'miniforge3'),
        (Join-Path $env:ProgramData 'miniconda3'),
        (Join-Path $env:ProgramData 'anaconda3'),
        (Join-Path $env:ProgramData 'miniforge3')
    )) {
        $candidates += Join-Path $root 'Scripts\conda.exe'
    }

    $commands = @(Get-Command conda.exe -All -ErrorAction SilentlyContinue)
    $candidates += $commands | ForEach-Object { $_.Source }

    foreach ($candidate in @($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        try {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                continue
            }
            $null = & $candidate --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [System.IO.Path]::GetFullPath($candidate)
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Get-ProjectPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [string]$EnvironmentName = 'industry_agent'
    )

    $candidates = @()
    if ($env:INDUSTRY_AGENT_PYTHON) {
        $candidates += $env:INDUSTRY_AGENT_PYTHON
    }
    $candidates += Join-Path $ProjectRoot '.venv\Scripts\python.exe'

    foreach ($root in @(
        (Join-Path $env:USERPROFILE 'miniconda3'),
        (Join-Path $env:USERPROFILE 'anaconda3'),
        (Join-Path $env:USERPROFILE 'miniforge3'),
        (Join-Path $env:LOCALAPPDATA 'miniconda3'),
        (Join-Path $env:LOCALAPPDATA 'anaconda3'),
        (Join-Path $env:LOCALAPPDATA 'miniforge3'),
        (Join-Path $env:ProgramData 'miniconda3'),
        (Join-Path $env:ProgramData 'anaconda3'),
        (Join-Path $env:ProgramData 'miniforge3')
    )) {
        $candidates += Join-Path $root "envs\$EnvironmentName\python.exe"
    }

    $conda = Get-CondaExecutable
    if ($conda) {
        try {
            $jsonText = (& $conda info --envs --json 2>$null) -join "`n"
            if ($LASTEXITCODE -eq 0 -and $jsonText) {
                $environmentInfo = $jsonText | ConvertFrom-Json
                foreach ($environmentPath in @($environmentInfo.envs)) {
                    if ((Split-Path -Leaf $environmentPath) -eq $EnvironmentName) {
                        $candidates += Join-Path $environmentPath 'python.exe'
                    }
                }
            }
        }
        catch {
            # Common install locations and PATH are still checked below.
        }
    }

    $commands = @(Get-Command python.exe -All -ErrorAction SilentlyContinue)
    $candidates += $commands | ForEach-Object { $_.Source }

    foreach ($candidate in @($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        try {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                continue
            }
            $null = & $candidate -c 'import chromadb, streamlit, torch' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [System.IO.Path]::GetFullPath($candidate)
            }
        }
        catch {
            continue
        }
    }

    throw 'No compatible project Python was found. Run Setup-Windows.cmd first.'
}
