$ErrorActionPreference='Stop'
$review=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$terminal='C:\MT5\EAAI_V3103_Tester_20260828\Doo Technology MetaTrader 5'
$source=Join-Path $review '01_BROKER_DATA\EXPORTER\R5ReviewBarExporter.mq5'
$compileLog=Join-Path $review '01_BROKER_DATA\EXPORTER\compile.log'
& (Join-Path $terminal 'MetaEditor64.exe') ('/compile:'+$source) ('/log:'+$compileLog)
for($i=0;$i -lt 30;$i++){Start-Sleep -Seconds 1;if((Test-Path $compileLog)-and((Get-Content $compileLog -Tail 1)-match '^Result:')){break}}
$result=Get-Content $compileLog -Tail 1
if($result -notmatch 'Result: 0 errors, 0 warnings'){throw "Exporter compile failed: $result"}
$expertDir=Join-Path $terminal 'MQL5\Experts\R5Review'
New-Item -ItemType Directory -Path $expertDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $review '01_BROKER_DATA\EXPORTER\R5ReviewBarExporter.ex5') -Destination (Join-Path $expertDir 'R5ReviewBarExporter.ex5') -Force
$terminalExe=(Join-Path $terminal 'terminal64.exe')
Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" |
 Where-Object {$_.ExecutablePath -eq $terminalExe} |
 ForEach-Object {Stop-Process -Id $_.ProcessId -Force}
Start-Sleep -Seconds 1
$runs=@(
 @{Tag='2025_MARCH';From='2025.02.26';To='2025.04.04'},
 @{Tag='2025_APRIL';From='2025.03.29';To='2025.05.04'},
 @{Tag='2025_SEPTEMBER';From='2025.08.29';To='2025.10.04'},
 @{Tag='2026_MARCH';From='2026.02.26';To='2026.04.04'},
 @{Tag='2026_MAY';From='2026.04.28';To='2026.06.04'},
 @{Tag='AUGUST';From='2026.07.29';To='2026.09.04'}
)
$configDir=Join-Path $review '01_BROKER_DATA\EXPORTER\CONFIGS'
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
foreach($run in $runs){
 $report="Reports\R5_REVIEW_EXPORT_$($run.Tag).htm"
 $ini=Join-Path $configDir "$($run.Tag).ini"
 $content=@"
[Tester]
Expert=R5Review\R5ReviewBarExporter.ex5
Symbol=XAUUSD.s
Period=M5
Optimization=0
Model=4
FromDate=$($run.From)
ToDate=$($run.To)
ForwardMode=0
Deposit=10000
Currency=USD
Leverage=100
ExecutionMode=162
Visual=0
UseLocal=1
UseRemote=0
UseCloud=0
Report=$report
ReplaceReport=1
ShutdownTerminal=1

[TesterInputs]
InpOutputTag=$($run.Tag)
"@
 Set-Content -LiteralPath $ini -Value $content -Encoding unicode
 Write-Output "START $($run.Tag)"
 $p=Start-Process -FilePath (Join-Path $terminal 'terminal64.exe') -ArgumentList @('/portable',('/config:'+$ini)) -WorkingDirectory $terminal -WindowStyle Hidden -Wait -PassThru
 if($p.ExitCode -ne 0){throw "Exporter run failed $($run.Tag): $($p.ExitCode)"}
 Write-Output "DONE $($run.Tag)"
}
$common=Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\R5_TRADE_REVIEW'
if(-not(Test-Path $common)){throw "Common export folder missing: $common"}
$destination=Join-Path $review '01_BROKER_DATA\TESTER_EXPORT'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -Path (Join-Path $common '*.csv') -Destination $destination -Force
Write-Output $result
Get-ChildItem -LiteralPath $destination | Select-Object Name,Length
