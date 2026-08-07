function Test-AgencyCrmHealth {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200) -and ($response.Content -like '*"status":"ok"*')
    }
    catch {
        return $false
    }
}
