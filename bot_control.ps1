param(
    [ValidateSet("status", "start", "stop", "toggle")]
    [string]$Action = "status"
)

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BotScript = Join-Path $ProjectDir "main.py"
$LogFile = Join-Path $ProjectDir "bot.log"
$PidFile = Join-Path $ProjectDir "bot.pid"

function Get-BotProcess {
    Get-WmiObject Win32_Process | Where-Object {
        $_.CommandLine -like "*python*main.py*" -or
        ($_.CommandLine -like "*python*" -and $_.CommandLine -like "*main.py*")
    } | Select-Object -First 1
}

function Write-Status {
    param([string]$Message, [string]$Status)
    $Output = @{
        status  = $Status
        message = $Message
    }
    $Output | ConvertTo-Json -Compress
}

function Show-Notification {
    param([string]$Text, [string]$Title = "Bot Control")
    try {
        $Toast = New-Object -ComObject Wscript.Shell
        $Toast.Popup($Text, 3, $Title, 0) | Out-Null
    } catch {
        Write-Host "$Title : $Text"
    }
}

switch ($Action) {
    "status" {
        $proc = Get-BotProcess
        if ($proc) {
            Write-Status "BOT_RUNNING" "Бот запущен (PID: $($proc.ProcessId))"
        } else {
            Write-Status "BOT_STOPPED" "Бот остановлен"
        }
        break
    }

    "start" {
        $proc = Get-BotProcess
        if ($proc) {
            Write-Status "ALREADY_RUNNING" "Бот уже запущен (PID: $($proc.ProcessId))"
            break
        }

        try {
            $python = "python"
            $args = @($BotScript)

            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $python
            $psi.Arguments = $args
            $psi.WorkingDirectory = $ProjectDir
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true

            $p = [System.Diagnostics.Process]::Start($psi)
            $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal

            $p.Id | Out-File -FilePath $PidFile -Force
            Start-Sleep -Seconds 2

            if (!$p.HasExited) {
                Show-Notification -Text "Бот уведомлений запущен" -Title "Bot Control"
                Write-Status "STARTED" "Бот запущен (PID: $($p.Id))"
            } else {
                $stderr = $p.StandardError.ReadToEnd()
                Write-Status "START_FAILED" "Ошибка запуска: $stderr"
            }
        } catch {
            Write-Status "ERROR" "Ошибка: $_"
        }
        break
    }

    "stop" {
        $proc = Get-BotProcess
        if (!$proc) {
            Write-Status "NOT_RUNNING" "Бот не запущен"
            break
        }

        try {
            $proc.Terminate() | Out-Null
            if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
            Show-Notification -Text "Бот уведомлений остановлен" -Title "Bot Control"
            Write-Status "STOPPED" "Бот остановлен"
        } catch {
            Write-Status "ERROR" "Ошибка остановки: $_"
        }
        break
    }

    "toggle" {
        $proc = Get-BotProcess
        if ($proc) {
            & $MyInvocation.MyCommand.Path -Action stop
        } else {
            & $MyInvocation.MyCommand.Path -Action start
        }
        break
    }
}
