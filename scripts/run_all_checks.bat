@echo off
REM Runs every check: unit/integration tests, the three live race scripts,
REM the benchmark (--quick), and the browser smoke test if Playwright is
REM installed. Prints PASS/FAIL per step; exits 1 if any step failed.
REM
REM   scripts\run_all_checks.bat                       (uses "python" on PATH)
REM   set PYTHON=venv\Scripts\python.exe
REM   scripts\run_all_checks.bat
REM
REM Needs PostgreSQL running locally. The race scripts use the dev database
REM from .env; the jobs runner is disabled for them so a check run never
REM expires real pending bookings.
setlocal
cd /d "%~dp0.."
if "%PYTHON%"=="" set "PYTHON=python"
set "OVERALL=0"
set "SUMFILE=%TEMP%\resv_checks_summary.txt"
type nul > "%SUMFILE%"

call :step "pytest" "%PYTHON% -m pytest -q"
set "JOBS_ENABLED=false"
call :step "race: concurrency_test" "%PYTHON% tests\concurrency_test.py"
call :step "race: quota_race_test" "%PYTHON% tests\quota_race_test.py"
call :step "race: capacity_race_test" "%PYTHON% tests\capacity_race_test.py"
set "JOBS_ENABLED="
call :step "benchmark --quick" "%PYTHON% scripts\benchmark_naive_vs_engine.py --quick"

"%PYTHON%" -c "import playwright" >nul 2>&1
if errorlevel 1 (
  echo   e2e smoke: SKIP ^(playwright not installed^)>> "%SUMFILE%"
) else (
  call :step "e2e smoke" "%PYTHON% tests\e2e\smoke_test.py"
)

echo.
echo ================ SUMMARY ================
type "%SUMFILE%"
echo =========================================
if "%OVERALL%"=="0" (echo ALL CHECKS PASSED) else (echo SOME CHECKS FAILED)
exit /b %OVERALL%

REM ---- :step "<name>" "<command line>" -------------------------------------
:step
echo.
echo === %~1 ===
%~2
if errorlevel 1 (
  set "OVERALL=1"
  echo   %~1: FAIL>> "%SUMFILE%"
) else (
  echo   %~1: PASS>> "%SUMFILE%"
)
exit /b 0
