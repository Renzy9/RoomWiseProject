$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-PythonProbe {
    param([string]$Executable, [string[]]$Arguments)
    # Windows PowerShell 5.1 can turn native stderr into a terminating error.
    # A failed candidate must not prevent checking the next Python installation.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $probeOutput = @(& $Executable @Arguments 2>$null)
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $probeOutput }
    } catch {
        return [pscustomobject]@{ ExitCode = 1; Output = @() }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

try {
    # Select only candidates whose Python version and model packages both work.
    $probeCode = "import sys; assert sys.version_info >= (3, 11); import flask, pandas, sklearn, numpy; assert sklearn.__version__ == '1.8.0'; print(sys.executable)"
    # Prefer the private runtime shipped with this copy of RoomWise.
    $roomwisePython = $null
    foreach ($relativePath in @('.runtime\python.exe', '.venv\Scripts\python.exe')) {
        $candidate = Join-Path $PSScriptRoot $relativePath
        if (Test-Path -LiteralPath $candidate) {
            $probe = Invoke-PythonProbe -Executable $candidate -Arguments @('-B', '-c', $probeCode)
            if ($probe.ExitCode -eq 0) {
                $roomwisePython = $candidate
                break
            }
        }
    }
    # Actually run Python; the Microsoft Store shortcut is not an installation.
    if (-not $roomwisePython) {
        foreach ($commandName in @('py', 'python')) {
            if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) { continue }
            $arguments = @('-B', '-c', $probeCode)
            if ($commandName -eq 'py') { $arguments = @('-3') + $arguments }
            $probe = Invoke-PythonProbe -Executable $commandName -Arguments $arguments
            $candidate = $probe.Output | Select-Object -Last 1
            if ($probe.ExitCode -eq 0 -and $candidate -and (Test-Path -LiteralPath "$candidate" -PathType Leaf)) {
                $roomwisePython = "$candidate"
                break
            }
        }
    }
    if (-not $roomwisePython) {
        throw 'No usable Python environment was found. RoomWise needs Python 3.11 or newer and the packages in requirements.txt, including scikit-learn 1.8.0. Install them into .venv or restore the complete .runtime folder.'
    }

    Write-Host 'Starting RoomWise at http://127.0.0.1:5080/'
    Write-Host 'Keep this window open while using the website. Press Ctrl+C to stop.'
    & $roomwisePython -B (Join-Path $PSScriptRoot 'app.py')
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
