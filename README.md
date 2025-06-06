# BVShop 批次上架工具

## 功能簡介

- 多商品資料夾批次自動上架（含主圖、描述圖、規格、SEO、Cloudflare防護）
- 美觀省資源的 GUI 介面，可一鍵開始/暫停/重跑失敗商品
- 每次失敗自動記錄，方便補上架
- 完整 log 與 debug 截圖

## 目錄說明

| 檔案                      | 說明                    |
|--------------------------|-------------------------|
| `main.py`                | 啟動主程式              |
| `gui.py`                 | 主視覺化介面            |
| `batch_uploader.py`      | 批次上架主流程          |
| `up_single.py`           | 單商品自動上架邏輯      |
| `product_progress_item.py`| 單商品進度顯示元件      |
| `config.json`            | 帳密與預設設定          |
| `failed_list.json`       | 失敗商品清單（自動產生）|
| `dark_theme.qss`         | 主題樣式                |
| `install_requirements.bat`| Windows快速安裝依存套件 |

## 安裝依賴

請先安裝 Python 3.8~3.12（建議 64 位元）。

1. 建議直接執行本目錄下的 `install_requirements.bat`：
    ```
    install_requirements.bat
    ```

2. 或手動安裝依賴：
    ```
    pip install PyQt5 psutil aiohttp playwright
    python -m playwright install
    ```

## 執行方式

1. 直接點兩下 `main.py`（建議用 Python 3.8~3.12）。
2. 或在命令列輸入：
    ```
    python main.py
    ```
3. 開啟後，請設定來源資料夾、帳密、網域，即可批次上架。

## 常見問題

- **Q:** 換電腦要怎麼搬？
    - 只要複製整個資料夾到新電腦，並執行 `install_requirements.bat` 即可。
- **Q:** 失敗商品如何補跑？
    - 按下 GUI 的「重跑失敗商品」按鈕即可。
- **Q:** 主圖/描述圖格式？
    - 請使用 jpg、png、webp 格式。描述圖建議 jpg/png 以相容性最佳。

---