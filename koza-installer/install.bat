@echo off
REM Koza Kurulum Baslatici
REM Bu dosya kullanici cift tikladiginda PowerShell setup betigini calistirir.

echo Koza Setup baslatiliyor, lutfen bekleyin...
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup.ps1"
exit
