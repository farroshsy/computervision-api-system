param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$ApiKey = "test-api-key",
    [switch]$EnforceValidation
)

# Usage examples:
#   powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1 -ApiKey 'override_key'
#   powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1 -EnforceValidation
# Environment overrides (if parameters are not provided):
#   $env:OCR_API_BASE -> ApiBase (e.g. http://127.0.0.1:8001)
#   $env:OCR_API_KEY  -> ApiKey

# If caller didn't pass -ApiBase/-ApiKey, allow env-based overrides to make switching targets easy
if (-not $PSBoundParameters.ContainsKey('ApiBase')) {
    if ($env:OCR_API_BASE) { $ApiBase = $env:OCR_API_BASE }
}
if (-not $PSBoundParameters.ContainsKey('ApiKey')) {
    if ($env:OCR_API_KEY) { $ApiKey = $env:OCR_API_KEY }
}

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.IO

function Get-Json($uri) {
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add('X-API-Key', $ApiKey)
        return $wc.DownloadString($uri)
    } catch {
        return $_ | Out-String
    }
}

function Invoke-Multipart($endpoint, $filePath, $docType, $confidence='0.7') {
    if (-not (Test-Path $filePath)) {
        Write-Warning "File not found: $filePath"
        return
    }

    $handler = New-Object System.Net.Http.HttpClientHandler
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.DefaultRequestHeaders.Add('X-API-Key', $ApiKey)

    $uri = "$ApiBase$endpoint"
    $uri = "$uri`?enforce_validation=$([string]::Copy(($EnforceValidation.IsPresent).ToString().ToLower()))"

    $content = New-Object System.Net.Http.MultipartFormDataContent

    # file part
    $fs = [System.IO.File]::OpenRead($filePath)
    $fileContent = New-Object System.Net.Http.StreamContent($fs)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/jpeg')
    $fileName = [System.IO.Path]::GetFileName($filePath)
    $content.Add($fileContent, 'file', $fileName)

    # form fields
    $content.Add((New-Object System.Net.Http.StringContent($docType)), 'document_type')
    $content.Add((New-Object System.Net.Http.StringContent($confidence)), 'confidence_threshold')

    try {
        $resp = $client.PostAsync($uri, $content).GetAwaiter().GetResult()
        $body = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        Write-Host $body
    } catch {
        Write-Host ($_ | Out-String)
    } finally {
        $content.Dispose()
        $fileContent.Dispose()
        $fs.Dispose()
        $client.Dispose()
        $handler.Dispose()
    }
}

Write-Host "== GET /health ==" -ForegroundColor Cyan
Write-Host (Get-Json "$ApiBase/health")

function Test-FileEndpoint($path, $docType) {
    Write-Host "`n== POST /api/v1/ocr/file  [$docType]  ($path) ==" -ForegroundColor Green
    Invoke-Multipart '/api/v1/ocr/file' $path $docType '0.7'
}

# KTP samples
Test-FileEndpoint "newdata/input/KTP/ID_standard.jpeg" "KTP"
Test-FileEndpoint "newdata/input/KTP/ID_good.jpeg" "KTP"

# SIM sample
Test-FileEndpoint "newdata/input/SIM/DL_good.jpeg" "SIM"

# STNK sample
Test-FileEndpoint "newdata/input/STNK/STNK_standard.jpeg" "STNK"

# KIR sample
Test-FileEndpoint "newdata/input/KIR/KIR_standard.jpeg" "KIR"
