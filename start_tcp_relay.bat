@echo off
setlocal

:: 実行ファイルのディレクトリを取得
set "SCRIPT_DIR=%~dp0"
set "EXE_PATH=%SCRIPT_DIR%tcp_relay_server.exe"

:: PowerShell ウィンドウで `tcp_relay_server2.exe` を実行
start powershell -NoExit -Command "& '%EXE_PATH%' 127.0.0.1:9999 127.0.0.1:10000 --mode connect-listen --dump"

endlocal