param(
    [Parameter(Mandatory = $true)]
    [int]$Port
)

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    Write-Host "Port $Port is free."
    exit 0
}

$pids = $connections.OwningProcess | Sort-Object -Unique
foreach ($processId in $pids) {
    try {
        $proc = Get-Process -Id $processId -ErrorAction Stop
        Write-Host "Stopping $($proc.ProcessName) (PID $processId) on port $Port..."
        Stop-Process -Id $processId -Force -ErrorAction Stop
    }
    catch {
        Write-Warning "Could not stop PID ${processId}: $_"
    }
}

Write-Host "Port $Port released."
