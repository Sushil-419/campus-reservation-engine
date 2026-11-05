@echo off
echo Restarting PostgreSQL 17 to apply configuration...
net stop postgresql-x64-17
net start postgresql-x64-17
echo.
echo Status:
sc query postgresql-x64-17
pause
