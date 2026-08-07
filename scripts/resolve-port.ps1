param(
    [Parameter(Mandatory = $true)]
    [int]$PreferredPort,
    [int]$MaxAttempts = 20
)

function Test-PortInUse {
    param([Parameter(Mandatory = $true)][int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$connections
}

for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
    $candidate = $PreferredPort + $offset
    if (-not (Test-PortInUse -Port $candidate)) {
        Write-Output $candidate
        return
    }
}

throw "No free port found in range $PreferredPort..$($PreferredPort + $MaxAttempts - 1)"
