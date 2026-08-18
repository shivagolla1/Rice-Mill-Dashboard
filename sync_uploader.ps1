# Rice Mill Dashboard - Native 2-Click Cloud Sync Uploader (Zero-Python Required)
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
try { Add-Type -AssemblyName System.IO.Compression -ErrorAction SilentlyContinue } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ConfigFile = Join-Path $ScriptDir "sync_config.txt"

$CloudUrl = "https://ricemilldashboard.up.railway.app"
$LicenseKey = ""
$CompanyCode = ""
$SyncToken = "RiceMillSyncSecretToken2026!"

if (Test-Path $ConfigFile) {
    Get-Content $ConfigFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $k = $parts[0].Trim()
            $v = $parts[1].Trim()
            if ($k -eq "CLOUD_URL") { $CloudUrl = $v.TrimEnd('/') }
            if ($k -eq "LICENSE_KEY") { $LicenseKey = $v }
            if ($k -eq "COMPANY_CODE") { $CompanyCode = $v }
            if ($k -eq "SYNC_SECRET_TOKEN") { $SyncToken = $v }
        }
    }
}

# Open Windows File Explorer Picker
$FilePicker = New-Object System.Windows.Forms.OpenFileDialog
$FilePicker.Filter = "Access Database (*.mdb)|*.mdb|All Files (*.*)|*.*"
$FilePicker.Title = "Select Access Database (.mdb) File to Sync to Dashboard"

$Result = $FilePicker.ShowDialog()
if ($Result -ne [System.Windows.Forms.DialogResult]::OK) {
    exit
}

$MdbPath = $FilePicker.FileName
$FileName = [System.IO.Path]::GetFileName($MdbPath)

try {
    # Read & GZIP compress bytes in RAM
    $RawBytes = [System.IO.File]::ReadAllBytes($MdbPath)
    $Ms = New-Object System.IO.MemoryStream
    $GzipStream = New-Object System.IO.Compression.GZipStream($Ms, [System.IO.Compression.CompressionMode]::Compress)
    $GzipStream.Write($RawBytes, 0, $RawBytes.Length)
    $GzipStream.Close()
    $CompressedBytes = $Ms.ToArray()
    $Ms.Close()

    # Convert compressed bytes to Base64 (eliminates binary stream locks on Windows 7)
    $B64Data = [System.Convert]::ToBase64String($CompressedBytes)
    $Endpoint = "$CloudUrl/api/sync-database"
    $JsonPayload = "{`"data`":`"$B64Data`",`"chunk_idx`":0,`"total_chunks`":1}"

    $ResponseStr = ""

    # Strategy 1: Native Windows C++ COM Engine (WinHttp.WinHttpRequest.5.1) - Bypasses .NET Schannel bugs on Win7
    try {
        $WinHttp = New-Object -ComObject WinHttp.WinHttpRequest.5.1
        # Option 9: Enable TLS 1.2 (2048) + TLS 1.1 (512) + TLS 1.0 (128) = 2688
        try { $WinHttp.Option(9) = 2688 } catch { try { $WinHttp.Option(9) = 2048 } catch {} }
        # Option 4: Ignore SSL Cert Errors if any
        try { $WinHttp.Option(4) = 13056 } catch {}

        $WinHttp.Open("POST", $Endpoint, $false)
        $WinHttp.SetRequestHeader("Content-Type", "application/json")
        if ($LicenseKey) { $WinHttp.SetRequestHeader("X-License-Key", $LicenseKey) }
        if ($CompanyCode) { $WinHttp.SetRequestHeader("X-Company-Code", $CompanyCode) }

        $WinHttp.Send($JsonPayload)
        $ResponseStr = $WinHttp.ResponseText
    } catch {
        # Strategy 2: Native PowerShell HttpWebRequest with Base64 JSON payload
        [System.Net.ServicePointManager]::Expect100Continue = $false
        [System.Net.ServicePointManager]::CheckCertificateRevocationList = $false
        try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true} } catch {}
        try {
            [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]3072 -bor [System.Net.SecurityProtocolType]768 -bor [System.Net.SecurityProtocolType]192 -bor [System.Net.SecurityProtocolType]48
        } catch {}

        $JsonBytes = [System.Text.Encoding]::UTF8.GetBytes($JsonPayload)
        $Request = [System.Net.HttpWebRequest]::Create($Endpoint)
        $Request.Method = "POST"
        $Request.ContentType = "application/json"
        $Request.ContentLength = $JsonBytes.Length
        if ($LicenseKey) { $Request.Headers.Add("X-License-Key", $LicenseKey) }
        if ($CompanyCode) { $Request.Headers.Add("X-Company-Code", $CompanyCode) }
        $Request.Timeout = 90000
        $Request.KeepAlive = $false

        $ReqStream = $Request.GetRequestStream()
        $ReqStream.Write($JsonBytes, 0, $JsonBytes.Length)
        $ReqStream.Close()

        $Response = $Request.GetResponse()
        $RespStream = $Response.GetResponseStream()
        $Reader = New-Object System.IO.StreamReader($RespStream)
        $ResponseStr = $Reader.ReadToEnd()
        $Reader.Close()
        $Response.Close()
    }

    $MillName = if ($CompanyCode) { $CompanyCode } else { "Dashboard" }
    if ($ResponseStr -match '"company_name"\s*:\s*"([^"]+)"') {
        $MillName = $Matches[1]
    } else {
        try {
            $JsonResp = $ResponseStr | ConvertFrom-Json
            if ($JsonResp.company_name) { $MillName = $JsonResp.company_name }
        } catch {}
    }

    [System.Windows.Forms.MessageBox]::Show("Database File '$FileName' Synced Successfully to $MillName!", "Rice Mill Dashboard", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)

} catch {
    $ErrMsg = $_.Exception.Message
    if ($_.Exception.Response) {
        try {
            $Reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $ErrMsg = $Reader.ReadToEnd()
        } catch {}
    }
    [System.Windows.Forms.MessageBox]::Show("Sync Failed: " + $ErrMsg, "Rice Mill Sync Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
}





