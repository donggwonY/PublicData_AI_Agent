#!/usr/bin/env bash
# E-05 공실 해소 기간 실험 전체 재실행(최종 v2 순서). 사용법은 README.md.
#   E05_WORK : 작업 폴더(input/ 에 고정 빌드 8개 파일). E05_AUX : 보조 자료 폴더.
#   PY       : 실험 환경 python (requirements.txt). SVC_PY : service/.venv python(0단계만).
set -euo pipefail
: "${E05_WORK:?}" "${E05_AUX:?}" "${PY:?}" "${SVC_PY:?}"
export E05_WORK E05_AUX
HERE=$(cd "$(dirname "$0")" && pwd)
(cd "$E05_WORK/input" && sha256sum -c "$HERE/../../docs/e05/results/input_sha256.txt") || { echo "입력 해시 불일치"; exit 1; }
"$SVC_PY" "$HERE/episodes.py"
for s in run_asof test_asof baseline models stage1_fix run_sangga test_sangga models_sangga final_test leakage_compare leakage_ablation; do
  echo "== $s $(date +%T)"
  "$PY" -W ignore "$HERE/$s.py" > "$E05_WORK/log_$s.txt" 2>&1 || { echo "FAILED $s"; tail -5 "$E05_WORK/log_$s.txt"; exit 1; }
  tail -2 "$E05_WORK/log_$s.txt"
done
echo "== ALL DONE $(date +%T)"
