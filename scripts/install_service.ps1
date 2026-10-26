# StrutCalc Knowledge Assistant - NSSM service installation.
# Run as Administrator.
#
# Wraps `uvicorn app.main:app` as a Windows service so the backend (and the web
# UI it serves) runs non-stop and restarts on crash or boot. The MCP search
# server is NOT a service: the backend spawns it on demand (stdio) per request.
#
# Note: the backend calls Bedrock using the AWS SSO token cached under
# C:\Users\<user>\.aws. The service MUST run as that same interactive user, or
# it cannot see the cache and every answer fails auth. It defaults to the
# TENNECO\patrbato account for this reason. Windows requires the account's
# password to register a service under a named user; the script prompts for it
# securely when it is not passed in.

param(
    [string]$ServiceName = "StrutCalcKnowledge",
    [string]$ServiceUser = ".\patrbato",
    [string]$ServicePassword = "",
    [int]$Port = 8077,
    [switch]$Uninstall,
    [switch]$AutoStart
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$UvicornPath = Join-Path $ProjectDir ".venv\Scripts\uvicorn.exe"
$LogDir = Join-Path $ProjectDir "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ---- Find or install NSSM (scoop -> chocolatey -> direct download) ----
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
$LocalNssm = Join-Path $ScriptDir "nssm.exe"
if (-not $nssm -and (Test-Path $LocalNssm)) {
    $env:Path += ";$ScriptDir"
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
}
if (-not $nssm) {
    if (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install nssm
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install nssm -y
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
        $NssmZip = Join-Path $ScriptDir "nssm.zip"
        $NssmTempDir = Join-Path $ScriptDir "nssm_temp"
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
        Expand-Archive -Path $NssmZip -DestinationPath $NssmTempDir -Force
        Copy-Item (Join-Path $NssmTempDir "nssm-2.24\win64\nssm.exe") $ScriptDir
        Remove-Item $NssmZip -Force; Remove-Item $NssmTempDir -Recurse -Force
        $env:Path += ";$ScriptDir"
    }
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) { Write-Host "NSSM install failed." -ForegroundColor Red; exit 1 }
}

# ---- Uninstall mode ----
if ($Uninstall) {
    try { nssm stop $ServiceName } catch {} 2>$null
    try { nssm remove $ServiceName confirm } catch {} 2>$null
    Write-Host "Service '$ServiceName' removed." -ForegroundColor Green
    exit 0
}

# ---- Remove old if present ----
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    try { nssm stop $ServiceName } catch {} 2>$null
    try { nssm remove $ServiceName confirm } catch {} 2>$null
}

if (-not (Test-Path $UvicornPath)) {
    Write-Host "uvicorn not found at $UvicornPath - run 'uv sync' first." -ForegroundColor Red
    exit 1
}

# ---- Install ----
nssm install $ServiceName $UvicornPath
nssm set $ServiceName AppParameters "app.main:app --host 0.0.0.0 --port $Port"
nssm set $ServiceName AppDirectory $ProjectDir
nssm set $ServiceName DisplayName "StrutCalc Knowledge Assistant"
nssm set $ServiceName Description "FastAPI backend + web UI for the local semantic code-search assistant. Spawns the MCP search server on demand."

# Logging (rotated at 10 MB, appended).
$StdoutLog = Join-Path $LogDir "service.log"
$StderrLog = Join-Path $LogDir "service-error.log"
nssm set $ServiceName AppStdout $StdoutLog
nssm set $ServiceName AppStderr $StderrLog
nssm set $ServiceName AppStdoutCreationDisposition 4
nssm set $ServiceName AppStderrCreationDisposition 4
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760

# Restart policy.
nssm set $ServiceName AppRestartDelay 5000
nssm set $ServiceName AppThrottle 10000

# Run as the interactive user so the service inherits that user's ~/.aws SSO
# cache and can reach Bedrock. Running as the default LocalSystem account would
# not see the cache, so refuse that silently-broken path and prompt for the
# password when it was not supplied.
if ($ServiceUser) {
    if (-not $ServicePassword) {
        $secure = Read-Host "Password for '$ServiceUser' (needed to run the service as this user)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $ServicePassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    nssm set $ServiceName ObjectName $ServiceUser $ServicePassword
    Write-Host "Service will run as '$ServiceUser' (inherits that user's AWS SSO cache)." -ForegroundColor Green
} else {
    Write-Host "WARNING: no ServiceUser set. The service will run as LocalSystem and" -ForegroundColor Yellow
    Write-Host "         will NOT see your AWS SSO cache, so Bedrock calls will fail." -ForegroundColor Yellow
}

nssm set $ServiceName Start SERVICE_AUTO_START

Write-Host "Service '$ServiceName' installed on port $Port." -ForegroundColor Green
Write-Host "  Start:  nssm start $ServiceName"
Write-Host "  Stop:   nssm stop $ServiceName"
Write-Host "  Status: nssm status $ServiceName"
Write-Host "  Logs:   Get-Content $StdoutLog -Tail 50 -Wait"

if ($AutoStart) {
    nssm start $ServiceName
    Start-Sleep -Seconds 2
    nssm status $ServiceName
} else {
    $start = Read-Host "Start service now? (y/n)"
    if ($start -eq "y") {
        nssm start $ServiceName
        Start-Sleep -Seconds 2
        nssm status $ServiceName
    }
}
