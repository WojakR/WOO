@echo off
rem Aplikacja Streamlit Asystenta Ocen Okresowych - start jednym kliknieciem (Windows).
rem Dziala z dowolnego miejsca: dwuklik albo skrot na pulpicie do tego pliku.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Nie znaleziono Pythona.
  echo Zainstaluj Python 3.10 lub nowszy z https://www.python.org/downloads/
  echo i zaznacz w instalatorze "Add python.exe to PATH". Potem uruchom ten plik ponownie.
  pause
  exit /b 1
)

%PY% frontend\start.py %*
if errorlevel 1 pause
