# Rice Mill Dashboard - Native 2-Click Cloud Sync Uploader (Zero-Python Required)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression

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

    # Prepare HTTPS Multipart Upload
    $Boundary = "----WebKitFormBoundary" + [Guid]::NewGuid().ToString("N")
    $Endpoint = "$CloudUrl/api/sync-database"

    $LF = "`r`n"
    $Header = "--$Boundary$LF" +
              "Content-Disposition: form-data; name=`"file`"; filename=`"$FileName`"$LF" +
              "Content-Type: application/octet-stream$LF$LF"
    $Footer = "$LF--$Boundary--$LF"

    $HeaderBytes = [System.Text.Encoding]::UTF8.GetBytes($Header)
    $FooterBytes = [System.Text.Encoding]::UTF8.GetBytes($Footer)

    $BodyStream = New-Object System.IO.MemoryStream
    $BodyStream.Write($HeaderBytes, 0, $HeaderBytes.Length)
    $BodyStream.Write($CompressedBytes, 0, $CompressedBytes.Length)
    $BodyStream.Write($FooterBytes, 0, $FooterBytes.Length)
    $BodyBytes = $BodyStream.ToArray()
    $BodyStream.Close()

    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $WebClient = New-Object System.Net.WebClient
    $WebClient.Headers.Add("Content-Type", "multipart/form-data; boundary=$Boundary")
    $WebClient.Headers.Add("X-License-Key", $LicenseKey)
    $WebClient.Headers.Add("X-Company-Code", $CompanyCode)


    $ResponseBytes = $WebClient.UploadData($Endpoint, "POST", $BodyBytes)
    $ResponseStr = [System.Text.Encoding]::UTF8.GetString($ResponseBytes)

    $MillName = if ($CompanyCode) { $CompanyCode } else { "Dashboard" }
    try {
        $JsonResp = $ResponseStr | ConvertFrom-Json
        if ($JsonResp.company_name) { $MillName = $JsonResp.company_name }
    } catch {}

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


