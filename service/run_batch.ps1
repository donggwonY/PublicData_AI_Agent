# 야간 배치: data/raw 의 인허가 CSV(증분 파일 포함) → data/processed 재계산
# 작업 스케줄러 등록 예 (매일 03:00):
#   schtasks /Create /SC DAILY /ST 03:00 /TN "DaeguLifecycleBatch" /TR "powershell -ExecutionPolicy Bypass -File C:\claude_workspace\PublicData_AI_Agent\service\run_batch.ps1"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\batch_$(Get-Date -Format yyyyMMdd).log"

# 배포와 같은 버전(Python 3.12 + requirements 고정 버전)으로 돌리기 위해 .venv 의 Python 만 쓴다.
# 시스템 python 은 패키지 버전이 달라 같은 parquet 가 나온다고 보장할 수 없다. 만드는 법은 README '빠른 시작'.
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    # 메시지는 ASCII 로 둔다: Windows PowerShell 5.1 은 BOM 없는 UTF-8 스크립트의 한글 문자열을 깨뜨린다.
    "[$(Get-Date -Format HH:mm:ss)] FAILED: .venv not found. Create it first (see README quick start)." | Tee-Object -FilePath $log -Append
    exit 1
}

& $python -m pipeline.build *>> $log
$code = $LASTEXITCODE
"[$(Get-Date -Format HH:mm:ss)] pipeline.build exit code $code" >> $log
exit $code
