#!/usr/bin/env bash
# Runs every check: unit/integration tests, the three live race scripts,
# the benchmark (--quick), and the browser smoke test if Playwright is
# installed. Prints PASS/FAIL per step; exits non-zero if any step failed.
#
#   scripts/run_all_checks.sh            (uses `python` on PATH)
#   PYTHON=venv/bin/python scripts/run_all_checks.sh
#
# Needs PostgreSQL running locally (see README). The race scripts use the
# dev database from .env; the jobs runner is disabled for them so a check
# run never expires real pending bookings.
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python}"
declare -a NAMES RESULTS
overall=0

run_step() {
  local name="$1"; shift
  echo
  echo "=== $name ==="
  if "$@"; then
    NAMES+=("$name"); RESULTS+=("PASS")
  else
    NAMES+=("$name"); RESULTS+=("FAIL"); overall=1
  fi
}

run_step "pytest" "$PY" -m pytest -q
run_step "race: concurrency_test" env JOBS_ENABLED=false "$PY" tests/concurrency_test.py
run_step "race: quota_race_test" env JOBS_ENABLED=false "$PY" tests/quota_race_test.py
run_step "race: capacity_race_test" env JOBS_ENABLED=false "$PY" tests/capacity_race_test.py
run_step "benchmark --quick" "$PY" scripts/benchmark_naive_vs_engine.py --quick
if "$PY" -c "import playwright" 2>/dev/null; then
  run_step "e2e smoke" "$PY" tests/e2e/smoke_test.py
else
  NAMES+=("e2e smoke"); RESULTS+=("SKIP (playwright not installed)")
fi

echo
echo "================ SUMMARY ================"
for i in "${!NAMES[@]}"; do
  printf "  %-28s %s\n" "${NAMES[$i]}" "${RESULTS[$i]}"
done
echo "========================================="
[ "$overall" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$overall"
