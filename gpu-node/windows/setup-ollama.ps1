<#
.SYNOPSIS
  Ollama на Windows для MediaMonitor: доступ из сети, контекст 8192, загрузка GigaChat 3.1 Lightning, проверка.

.DESCRIPTION
  Ollama ставится заранее: https://ollama.com/download (OllamaSetup.exe) или
  winget install --id Ollama.Ollama. Нужна версия 0.40.6 или новее.

  Скрипт задаёт переменные пользователя (их читает Ollama при старте):
    OLLAMA_HOST=0.0.0.0:11434     — слушать сеть, а не только этот компьютер;
    OLLAMA_CONTEXT_LENGTH=8192    — тот же контекст, что просит сервер (LLM_NUM_CTX): модель не перезагружается
                                    между запросами воронки (/api/chat) и сервера (/v1/chat/completions);
    OLLAMA_KEEP_ALIVE=-1          — модель не выгружается из памяти видеокарты.
  Потом перезапускает Ollama, скачивает модель и проверяет ответ по JSON-схеме.
  Доступ к порту 11434 закройте скриптом windows\firewall.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\setup-ollama.ps1
  powershell -ExecutionPolicy Bypass -File windows\setup-ollama.ps1 -Quant Q8_0
#>
param(
    [ValidateSet('Q4_K_M', 'Q6_K', 'Q8_0')]
    [string]$Quant = 'Q6_K',
    [int]$Context = 8192
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Model = "hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:$Quant"
$MinVersion = [version]'0.40.6'

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    throw 'Ollama не найдена. Поставьте её: https://ollama.com/download или winget install --id Ollama.Ollama'
}
$versionText = (& $ollama.Source --version) -join ' '
if ($versionText -match '(\d+\.\d+\.\d+)') {
    $version = [version]$Matches[1]
    Write-Host "Ollama $version"
    if ($version -lt $MinVersion) {
        Write-Warning "Нужна Ollama $MinVersion или новее (поддержка RTX 50xx и архитектуры GigaChat 3.1). Обновите её."
    }
}

$vars = @{
    OLLAMA_HOST           = '0.0.0.0:11434'
    OLLAMA_CONTEXT_LENGTH = "$Context"
    OLLAMA_KEEP_ALIVE     = '-1'
}
foreach ($name in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($name, $vars[$name], 'User')
    Set-Item "env:$name" $vars[$name]
    Write-Host "$name=$($vars[$name])"
}

Write-Host 'Перезапускаю Ollama, чтобы она прочитала переменные...'
Get-Process -Name 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
if (Test-Path $app) {
    Start-Process $app
} else {
    Start-Process -FilePath $ollama.Source -ArgumentList 'serve' -WindowStyle Hidden
}
$ready = $false
foreach ($i in 1..30) {
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) { throw 'Ollama не отвечает на http://127.0.0.1:11434 — запустите её из меню «Пуск».' }

Write-Host "Скачиваю $Model ..."
& $ollama.Source pull $Model
if ($LASTEXITCODE -ne 0) { throw "ollama pull завершился с ошибкой $LASTEXITCODE" }

$venvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $env:PYTHONUTF8 = '1'
    & $venvPython -m mm_embeddings.check --skip-torch --ollama http://127.0.0.1:11434 --model $Model
} else {
    Write-Host 'Проверка ответа по JSON-схеме:'
    $body = Get-Content (Join-Path $Root 'checks\ollama-chat.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $body.model = $Model
    $json = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 10))
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/chat' -Method Post -Body $json `
        -ContentType 'application/json; charset=utf-8' -TimeoutSec 300
    Write-Host $resp.message.content
    & $ollama.Source ps
}
Write-Host ''
Write-Host "На сервере: OLLAMA_URL=http://<адрес этого компьютера>:11434, OLLAMA_MODEL и LLM_MODEL = $Model"
