@echo off
echo 正在安裝 Python 套件...
pip install --upgrade pip
pip install PyQt5 psutil aiohttp playwright
python -m playwright install
echo.
echo 完成！請直接執行 main.py 開始使用。
pause