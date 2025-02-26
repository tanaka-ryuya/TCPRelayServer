@echo off
setlocal

:: 実行ファイルのディレクトリを取得
set "SCRIPT_DIR=%~dp0"
set "EXE_PATH=%SCRIPT_DIR%dist\tcp_relay_server.exe"

:: PowerShell ウィンドウで `tcp_relay_server2.exe` を実行
start powershell -NoExit -Command "& '%EXE_PATH%' 127.0.0.1:9999 127.0.0.1:10000 --mode connect-listen"
start powershell -NoExit -Command "& '%EXE_PATH%' 127.0.0.1:10000 127.0.0.1:10001 --mode connect-connect"
start powershell -NoExit -Command "& '%EXE_PATH%' 127.0.0.1:10001 127.0.0.1:10002 --mode listen-connect"
start powershell -NoExit -Command "& '%EXE_PATH%' 127.0.0.1:10002 127.0.0.1:10003 --mode listen-listen --dump"

endlocal