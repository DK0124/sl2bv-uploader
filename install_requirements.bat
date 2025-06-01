@echo off
REM 安裝 Python 相關依賴 (請確保已安裝 Python 並於 PATH)
echo 安裝 PyQt5、psutil、aiohttp、playwright...
pip install -U pip
pip install PyQt5 psutil aiohttp playwright
if %errorlevel% neq 0 (
    echo Python 套件安裝失敗，請檢查 Python 環境
    pause
    exit /b 1
)
echo 安裝 Playwright 瀏覽器驅動...
python -m playwright install
if %errorlevel% neq 0 (
    echo Playwright 瀏覽器安裝失敗！
    pause
    exit /b 1
)
echo 依賴安裝完成
pause