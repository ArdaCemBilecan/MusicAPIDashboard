# Music Dashboard: günlük veri çekimi (Windows)
#
# Linux'taki scripts/daily_fetch.sh + cron ikilisinin Windows karşılığı.
# Windows Görev Zamanlayıcı'ya (Task Scheduler) her gün 03:15'te çalışacak bir görev
# eklemek için PowerShell'de, proje klasöründeyken bir kez şunu çalıştırın:
#
#   $script = (Resolve-Path .\scripts\daily_fetch.ps1).Path
#   $action = New-ScheduledTaskAction -Execute "powershell.exe" `
#             -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
#   $trigger = New-ScheduledTaskTrigger -Daily -At 3:15am
#   Register-ScheduledTask -TaskName "MusicDashboard-DailyFetch" -Action $action -Trigger $trigger
#
# Görevi kaldırmak için:
#   Unregister-ScheduledTask -TaskName "MusicDashboard-DailyFetch" -Confirm:$false
#
# Not: Verinin veritabanına yazılması için consumer'ın (src/consumer.py) ve
# docker compose servislerinin çalışıyor olması gerekir.

# "Continue": Python'un stderr'e yazdığı loglar Windows PowerShell 5.1'de hata sayılmasın
$ErrorActionPreference = "Continue"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir ("fetch_{0:yyyy-MM-dd}.log" -f (Get-Date))
$KeepDays = 30

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Türkçe karakterler logda bozulmasın: Python çıktısı ve log dosyası UTF-8
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Write-Log([string]$Text) { Add-Content -Path $LogFile -Value $Text -Encoding UTF8 }

# Proje içindeki sanal ortamı tercih et, yoksa sistemdeki python
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

# Aynı anda iki çekim çalışmasın
$mutex = New-Object System.Threading.Mutex($false, "Global\MusicDashboardDailyFetch")
if (-not $mutex.WaitOne(0)) {
    Write-Log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Önceki çekim hâlâ çalışıyor, bu çalıştırma atlandı."
    exit 0
}

$exitCode = 0
try {
    Write-Log "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') günlük çekim başladı ====="
    Push-Location (Join-Path $ProjectDir "src")
    # stdout ve stderr aynı log dosyasına, satır satır ve UTF-8 olarak
    & $Python producer.py 2>&1 | ForEach-Object { Write-Log "$_" }
    $exitCode = $LASTEXITCODE
    $result = if ($exitCode -eq 0) { "bitti" } else { "HATA ile bitti (çıkış kodu $exitCode)" }
    Write-Log "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') günlük çekim $result ====="
}
finally {
    Pop-Location
    $mutex.ReleaseMutex()
    # Eski logları temizle
    Get-ChildItem -Path $LogDir -Filter "fetch_*.log" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
        Remove-Item -ErrorAction SilentlyContinue
}

exit $exitCode
