param(
    [Parameter(Mandatory = $true)]
    [int]$Port
)

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    Write-Host "[port $Port] free"
    exit 0
}

foreach ($processId in ($connections.OwningProcess | Sort-Object -Unique)) {
    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { "unknown" }
    Write-Host "[port $Port] in use by $name (PID $processId)"
}
