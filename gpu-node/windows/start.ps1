<#
.SYNOPSIS
  MediaMonitor, компьютер с видеокартой: ставит зависимости через uv и запускает сервис эмбеддингов.

.DESCRIPTION
  1. Ставит uv, если его нет (официальный установщик astral.sh).
  2. Создаёт .env из .env.example со случайным EMBEDDINGS_TOKEN, если .env ещё нет.
  3. Проверяет драйвер NVIDIA и ставит зависимости: uv sync --extra cu128 (torch 2.11.0, CUDA 12.8).
  4. Запускает сервис (порт 8090). Модель BERTA (~0,5 ГБ) скачивается при первом запуске; детектор
     ИИ-текста GigaCheck (14,3 ГБ) скачивается и грузится фоном после открытия порта (UPDATE-DETECTOR.md).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\start.ps1
  powershell -ExecutionPolicy Bypass -File windows\start.ps1 -Autostart        # + автозапуск при входе в Windows
  powershell -ExecutionPolicy Bypass -File windows\start.ps1 -RemoveAutostart
  powershell -ExecutionPolicy Bypass -File windows\start.ps1 -Torch cu130      # torch 2.14.1, драйвер >= 580
  powershell -ExecutionPolicy Bypass -File windows\start.ps1 -NoRun            # только установить и проверить
#>
param(
    [ValidateSet('cu128', 'cu130', 'cpu')]
    [string]$Torch = 'cu128',
    [switch]$Autostart,
    [switch]$RemoveAutostart,
    [switch]$NoRun,
    # Запуск из планировщика: без окна, журнал — в logs\.
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$TaskName = 'MediaMonitor embeddings'
$env:PYTHONUTF8 = '1'

if ($RemoveAutostart) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Автозапуск '$TaskName' удалён."
    return
}

# ---------------------------------------------------------------- 1. uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    $local = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (-not (Test-Path $local)) {
        Write-Host 'Ставлю uv (https://astral.sh/uv)...'
        powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
    }
    $uv = Get-Command $local
}
$UvExe = $uv.Source

# ---------------------------------------------------------------- 2. .env и токен
$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path $EnvFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $lines = Get-Content (Join-Path $Root '.env.example') -Encoding UTF8 |
        ForEach-Object { if ($_ -eq 'EMBEDDINGS_TOKEN=') { "EMBEDDINGS_TOKEN=$token" } else { $_ } }
    [IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
    Write-Host "Создан .env со случайным EMBEDDINGS_TOKEN. Скопируйте его значение в EMBEDDINGS_TOKEN на сервере."
}

# ---------------------------------------------------------------- 3. драйвер и зависимости
if ($Torch -ne 'cpu') {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) {
        Write-Warning 'nvidia-smi не найден: поставьте драйвер NVIDIA (https://www.nvidia.com/drivers).'
    } else {
        $gpu = (& $smi.Source --query-gpu=name,driver_version,memory.total --format=csv,noheader | Select-Object -First 1)
        Write-Host "Видеокарта: $gpu"
        $driver = [double](($gpu -split ',')[1].Trim() -replace '^(\d+\.\d+).*', '$1')
        $need = @{ cu128 = 570; cu130 = 580 }[$Torch]
        if ($driver -lt $need) {
            Write-Warning "Для -Torch $Torch нужен драйвер $need или новее, сейчас $driver. Обновите драйвер."
        }
    }
}

Write-Host "Ставлю зависимости: uv sync --extra $Torch ..."
& $UvExe sync --frozen --no-dev --extra $Torch
if ($LASTEXITCODE -ne 0) { throw "uv sync завершился с ошибкой $LASTEXITCODE" }

if (-not $Background) {
    & $UvExe run --frozen --no-dev --extra $Torch python -m mm_embeddings.check
}

# ---------------------------------------------------------------- автозапуск (по желанию)
if ($Autostart) {
    $taskArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Torch $Torch -Background"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArgs -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'MediaMonitor: сервис эмбеддингов BERTA (gpu-node)' -Force | Out-Null
    Write-Host "Автозапуск '$TaskName' включён: сервис стартует при входе пользователя $env:USERNAME."
    Write-Host "Журнал: $Root\logs\service.log. Запустить сейчас: Start-ScheduledTask -TaskName '$TaskName'"
}

if ($NoRun) { return }

# ---------------------------------------------------------------- 4. запуск
$runArgs = @('run', '--frozen', '--no-dev', '--extra', $Torch, 'mm-embeddings')
if ($Background) {
    $logs = Join-Path $Root 'logs'
    New-Item -ItemType Directory -Force $logs | Out-Null
    $p = Start-Process -FilePath $UvExe -ArgumentList $runArgs -WorkingDirectory $Root -NoNewWindow -Wait -PassThru `
        -RedirectStandardError (Join-Path $logs 'service.log') -RedirectStandardOutput (Join-Path $logs 'service.out.log')
    exit $p.ExitCode
} else {
    Write-Host 'Запускаю сервис (Ctrl+C — остановить)...'
    & $UvExe @runArgs
    exit $LASTEXITCODE
}
