<#
.SYNOPSIS
  Брандмауэр Windows: порты сервиса эмбеддингов (8090) и Ollama (11434) открыты только серверу MediaMonitor.

.DESCRIPTION
  У Ollama нет своей авторизации: кто достучался до порта 11434, тот пользуется моделью. Поэтому
  входящие подключения к портам разрешаются только с адреса сервера (или из локальной подсети).
  Скрипт также выключает правила «по программе» для ollama.exe и python.exe, которые Windows
  создаёт сама, когда при первом запуске нажимают «Разрешить доступ» (они открывают доступ всем)
  или «Отмена» (они блокируют и перебивают наши правила).

  Запускать от имени администратора.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\firewall.ps1 -ServerIp 192.168.1.20
  powershell -ExecutionPolicy Bypass -File windows\firewall.ps1 -ServerIp LocalSubnet   # вся локальная сеть
  powershell -ExecutionPolicy Bypass -File windows\firewall.ps1 -Remove
#>
#Requires -RunAsAdministrator
param(
    # Адрес сервера MediaMonitor (можно несколько через запятую) или LocalSubnet.
    [string[]]$ServerIp,
    [int[]]$Ports = @(8090, 11434),
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$Group = 'MediaMonitor gpu-node'

Get-NetFirewallRule -Group $Group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) {
    Write-Host "Правила группы '$Group' удалены."
    return
}
if (-not $ServerIp) { throw 'Укажите -ServerIp <адрес сервера> или -ServerIp LocalSubnet' }

foreach ($port in $Ports) {
    New-NetFirewallRule -DisplayName "MediaMonitor TCP $port" -Group $Group -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $port -RemoteAddress $ServerIp -Profile Any | Out-Null
    Write-Host "Разрешён вход на TCP $port только с: $($ServerIp -join ', ')"
}

# Правила «по программе» перебивают наши: разрешающие открывают порт всем, запрещающие закрывают его серверу.
$programs = Get-NetFirewallApplicationFilter | Where-Object {
    $_.Program -like '*\ollama*.exe' -or $_.Program -like '*\gpu-node\.venv\*' -or $_.Program -like '*\uv\python\*'
}
foreach ($rule in ($programs | Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' -and $_.Enabled -eq 'True' })) {
    Disable-NetFirewallRule -Name $rule.Name
    Write-Host "Выключено правило по программе: $($rule.DisplayName) ($($rule.Action))"
}

Write-Host ''
Write-Host 'Проверка с сервера:  curl http://<адрес этого компьютера>:8090/health'
Write-Host 'С другого адреса порты 8090 и 11434 должны быть закрыты (таймаут).'
