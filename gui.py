import sys
import os
import json
import time
import psutil
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QSpinBox, QGridLayout, QProgressBar, QFrame, QCheckBox, QComboBox, QSizePolicy, QDialog, QTextEdit
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont, QColor, QPalette

from batch_uploader import BVShopBatchUploader
from speed_controller import BehaviorMode

CONFIG_FILE = "config.json"
FAILED_LIST_FILE = "failed_list.json"

def suggest_max_workers():
    cpu = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total // (1024 ** 3)
    max_by_ram = max(1, int(ram_gb * 0.85 // 0.45))
    max_safe = min(cpu * 2, max_by_ram)
    return min(max_safe, 16)

class LogDialog(QDialog):
    def __init__(self, title, log_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - 詳細Log")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        label = QLabel(title)
        label.setStyleSheet("font-weight:bold;font-size:1.14em;margin-bottom:8px; color:#e6e6e6;")
        layout.addWidget(label)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlainText(log_text)
        self.log_edit.setStyleSheet("""
            background: #23293a;
            border-radius: 20px;
            color: #e0e6ef;
            font-size: 1.08em;
            padding: 18px;
        """)
        layout.addWidget(self.log_edit)
        btn = QPushButton("關閉")
        btn.setStyleSheet("""
            QPushButton {
                background: #2a3654;
                border: none;
                border-radius: 15px;
                padding: 12px 44px;
                font-size: 1.18em;
                color: #549cf6;
            }
            QPushButton:hover {
                background: #344769;
                color: #7ebdff;
            }
        """)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)
        self.setLayout(layout)

class ProductProgressItem(QWidget):
    def __init__(self, name, show_log_callback):
        super().__init__()
        self.setObjectName("ProductProgressItem")
        self.show_log_callback = show_log_callback
        self._log_text = ""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(30, 20, 30, 20)

        self.name_label = QLabel(name, self)
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        font = QFont("SF Pro Text", 10)
        font.setWeight(QFont.DemiBold)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("color:#bcc7d5; margin-bottom: 2px; letter-spacing:0.2px;")
        layout.addWidget(self.name_label, stretch=0)

        stat_hbox = QHBoxLayout()
        stat_hbox.setSpacing(13)
        self.status_icon = QLabel("⏳", self)
        self.status_icon.setFixedWidth(25)
        self.status_icon.setAlignment(Qt.AlignCenter)
        stat_hbox.addWidget(self.status_icon)
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setStyleSheet("font-size:1.09em; color: #e6e6e6; font-weight: 500;")
        stat_hbox.addWidget(self.status_label)
        layout.addLayout(stat_hbox, stretch=0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(32)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 14px;
                text-align: center;
                font-weight: 520;
                background: #22242c;
                color: #2c3e50;
                font-size: 1.15em;
                letter-spacing:0.3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #62b3ff, stop:0.5 #549cf6, stop:1 #7f53ff
                );
                border-radius: 14px;
            }
        """)
        layout.addWidget(self.progress_bar, stretch=0)

        self.progress_bar.mousePressEvent = self.show_log
        self.mousePressEvent = self.show_log

        self.setStyleSheet("""
            QWidget#ProductProgressItem {
                border: 2.2px solid #282b3c;
                border-radius: 32px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #23293a, stop:1 #1a1c23
                );
            }
            QWidget#ProductProgressItem:hover {
                border: 2.2px solid #62b3ff;
                background: #262a38;
            }
        """)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def update_progress(self, percent, detail_log):
        self.progress_bar.setValue(percent)
        if detail_log:
            self._log_text += ("\n" if self._log_text else "") + detail_log

    def set_status(self, success, elapsed, detail_log):
        if success is None:
            self.status_icon.setText("⏳")
            self.status_label.setText("下載中")
        elif success:
            self.status_icon.setText("✅")
            self.status_label.setText(f"<span style='color:#61e396'>上架完成</span>")
        else:
            self.status_icon.setText("❌")
            self.status_label.setText("<span style='color:#ff8686'>上架失敗</span>")
        if detail_log:
            self._log_text += ("\n" if self._log_text else "") + detail_log

    def show_log(self, event):
        self.show_log_callback(self.name_label.text(), self._log_text or "（暫無Log）")

class BVShopMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BVShop 上架監控")
        self.resize(1920, 1080)
        self.bv_batch_uploader = None
        self.product_status = {}
        self.product_widgets = {}
        self.total_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None
        self.is_paused = False
        self.has_started = False
        self.init_ui()
        self.load_config()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(32)
        main_layout.setContentsMargins(90, 60, 90, 60)

        ctl_wrap = QFrame()
        ctl_wrap.setFrameShape(QFrame.StyledPanel)
        ctl_wrap.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #23293a, stop:1 #181a20);
            border-radius: 34px; border:none;
        """)
        ctl_layout = QVBoxLayout()
        ctl_layout.setSpacing(20)
        ctl_layout.setContentsMargins(44, 32, 44, 32)

        row1 = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("來源資料夾")
        self.dir_edit.setStyleSheet("padding:14px 28px; border-radius:18px; background:#20222c; color:#e6e6e6; font-size:1.10em;")
        self.dir_btn = QPushButton("選擇")
        self.dir_btn.setCursor(Qt.PointingHandCursor)
        self.dir_btn.setStyleSheet("padding:12px 44px; border-radius:16px; font-size:1.10em; background:#232b3b; color:#549cf6;")
        self.dir_btn.clicked.connect(self.choose_dir)
        row1.addWidget(QLabel("來源資料夾:"))
        row1.addWidget(self.dir_edit, 2)
        row1.addWidget(self.dir_btn)
        ctl_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("帳號")
        self.username_edit.setStyleSheet("padding:12px 22px; border-radius:15px; background:#20222c; color:#e6e6e6;")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密碼")
        self.password_edit.setStyleSheet("padding:12px 22px; border-radius:15px; background:#20222c; color:#e6e6e6;")
        row2.addWidget(QLabel("帳號:"))
        row2.addWidget(self.username_edit, 1)
        row2.addWidget(QLabel("密碼:"))
        row2.addWidget(self.password_edit, 1)
        ctl_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.threads_spin = QSpinBox()
        self.threads_spin.setMinimum(1)
        self.suggested_workers = suggest_max_workers()
        self.threads_spin.setMaximum(9999)
        self.threads_spin.setValue(self.suggested_workers)
        self.threads_spin.setStyleSheet("padding:12px 22px; border-radius:15px; background:#20222c; color:#e6e6e6;")
        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("前台主網域（如 https://gd.bvshop.tw）")
        self.domain_edit.setStyleSheet("padding:12px 22px; border-radius:15px; background:#20222c; color:#e6e6e6;")
        row3.addWidget(QLabel("同時上架數:"))
        row3.addWidget(self.threads_spin)
        row3.addWidget(QLabel("主網域:"))
        row3.addWidget(self.domain_edit, 2)
        ctl_layout.addLayout(row3)

        row4 = QHBoxLayout()
        self.headless_checkbox = QCheckBox("無頭瀏覽器(效能較佳)")
        self.headless_checkbox.setChecked(True)
        self.behavior_mode_combo = QComboBox()
        self.behavior_mode_combo.addItems(["自動（建議）", "極速", "安全"])
        self.behavior_mode_combo.setStyleSheet("padding:12px 22px; border-radius:15px; background:#20222c; color:#e6e6e6;")
        row4.addWidget(self.headless_checkbox)
        row4.addWidget(QLabel("上架速度模式:"))
        row4.addWidget(self.behavior_mode_combo)
        ctl_layout.addLayout(row4)

        ctl_wrap.setLayout(ctl_layout)
        main_layout.addWidget(ctl_wrap)

        self.summary_label = QLabel("尚未開始")
        self.summary_label.setStyleSheet("font-size: 1.33em; font-weight:600; margin-bottom:14px; color:#e6e6e6;")
        main_layout.addWidget(self.summary_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("尚未開始")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                height: 56px;
                border: none;
                border-radius: 26px;
                background: #19202b;
                text-align: center;
                font-size: 1.36em;
                font-weight: bold;
                color: #2c3e50;
                margin: 30px 130px 26px 130px;
                min-width: 1100px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #62b3ff, stop:0.7 #549cf6, stop:1 #7f53ff);
                border-radius: 26px;
            }
        """)
        self.overall_progress.setVisible(False)
        main_layout.addWidget(self.overall_progress, alignment=Qt.AlignHCenter)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(54)
        self.grid_layout.setContentsMargins(66, 40, 66, 40)
        self.grid_container.setLayout(self.grid_layout)
        main_layout.addWidget(self.grid_container, stretch=1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始批次上架")
        self.pause_resume_btn = QPushButton("暫停")
        self.pause_resume_btn.setEnabled(False)
        self.retry_failed_btn = QPushButton("重跑失敗商品")
        self.exit_btn = QPushButton("結束程式")
        for btn in [self.start_btn, self.pause_resume_btn, self.retry_failed_btn, self.exit_btn]:
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #232b3b;
                    border: none;
                    border-radius: 22px;
                    padding: 22px 78px;
                    font-size: 1.19em;
                    color: #549cf6;
                    letter-spacing:0.03em;
                }
                QPushButton:hover {
                    background: #344769;
                    color: #7ebdff;
                }
            """)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_resume_btn)
        btn_layout.addWidget(self.retry_failed_btn)
        btn_layout.addWidget(self.exit_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.start_btn.clicked.connect(self.start_batch_upload)
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume)
        self.retry_failed_btn.clicked.connect(self.retry_failed_uploads)
        self.exit_btn.clicked.connect(self.close)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self.update_time_estimate)
        self.setMinimumSize(1920, 1080)

        app_palette = self.palette()
        app_palette.setColor(QPalette.Window, QColor("#181a20"))
        app_palette.setColor(QPalette.Base, QColor("#20222c"))
        app_palette.setColor(QPalette.Text, QColor("#e6e6e6"))
        app_palette.setColor(QPalette.Button, QColor("#232b3b"))
        self.setPalette(app_palette)

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "選擇來源資料夾")
        if d:
            self.dir_edit.setText(d)

    def load_config(self):
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.username_edit.setText(data.get("username", ""))
                self.password_edit.setText(data.get("password", ""))
                self.domain_edit.setText(data.get("domain", ""))
            except Exception as e:
                print(f"載入帳密設定失敗: {e}")

    def save_config(self):
        data = {
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
            "domain": self.domain_edit.text()
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"儲存帳密設定失敗: {e}")

    def get_behavior_mode(self):
        idx = self.behavior_mode_combo.currentIndex()
        if idx == 0:
            return BehaviorMode.AUTO
        elif idx == 1:
            return BehaviorMode.SPEED
        else:
            return BehaviorMode.SAFE

    def start_batch_upload(self):
        self.save_config()
        src_dir = self.dir_edit.text()
        username = self.username_edit.text()
        password = self.password_edit.text()
        threads = self.threads_spin.value()
        domain = self.domain_edit.text().strip()
        headless = self.headless_checkbox.isChecked()
        behavior_mode = self.get_behavior_mode()
        if not os.path.isdir(src_dir):
            self.summary_label.setText("來源資料夾不存在")
            return
        if not domain:
            self.summary_label.setText("請輸入主網域")
            return
        product_dirs = []
        for name in os.listdir(src_dir):
            pdir = os.path.join(src_dir, name)
            if os.path.isdir(pdir) and \
               os.path.exists(os.path.join(pdir, "product_info.json")) and \
               os.path.exists(os.path.join(pdir, "product_output.json")):
                product_dirs.append(pdir)
        self.total_count = len(product_dirs)
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.product_status.clear()
        self.clear_widgets()
        self.has_started = True
        self.overall_progress.setVisible(True)
        self.pause_resume_btn.setEnabled(True)
        self.pause_resume_btn.setText("暫停")
        for p in product_dirs:
            pname = os.path.basename(p)
            self.product_status[pname] = {
                "status": "waiting", "progress": 0, "log": "", "widget": None
            }
        self.update_summary()
        self.refresh_widgets()

        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            behavior_mode=behavior_mode,
            speed_status_callback=None,
            round_status_callback=None
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)
        self.bv_batch_uploader.paused_signal.connect(self.on_paused)
        self.bv_batch_uploader.resumed_signal.connect(self.on_resumed)

        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        self.is_paused = False

    def update_product_progress(self, product_name, percent, success, elapsed, detail_log):
        status = self.product_status.get(product_name)
        if not status:
            return
        status["progress"] = percent
        if detail_log:
            status["log"] = (status["log"] + "\n" + detail_log).strip()
        if success is None:
            status["status"] = "running"
        elif success:
            status["status"] = "success"
            self.success_count += 1
        else:
            status["status"] = "fail"
            self.fail_count += 1

        if status["status"] in ["running", "fail"]:
            if not status.get("widget"):
                status["widget"] = ProductProgressItem(product_name, self.show_log_dialog)
                self.product_widgets[product_name] = status["widget"]
                self.re_layout_grid()
            status["widget"].update_progress(percent, detail_log)
            status["widget"].set_status(success, elapsed, detail_log)
        else:
            if status.get("widget"):
                self.remove_widget(product_name)
                status["widget"] = None

        self.update_summary()

    def show_log_dialog(self, product_name, log_text):
        dlg = LogDialog(product_name, log_text, self)
        dlg.exec_()

    def batch_all_done(self, total, success, fail, fail_list):
        self.estimate_timer.stop()
        elapsed = int(time.time() - self.start_time)
        self.overall_progress.setValue(100)
        self.overall_progress.setFormat("100% 已完成")
        self.summary_label.setText(
            f"全部完成：成功 {success}/{total}，失敗 {fail}　總花費 {elapsed // 60}分{elapsed % 60}秒"
        )
        self.save_failed_list(fail_list)
        self.pause_resume_btn.setEnabled(False)
        self.is_paused = False

    def update_time_estimate(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        done = self.success_count + self.fail_count
        total = self.total_count
        if done > 0 and total > done:
            avg = elapsed / done
            remaining = total - done
            left = int(avg * remaining)
            self.summary_label.setText(
                f"{self.summary_label.text()}　預估剩餘 {left // 60}分{left % 60}秒"
            )

    def update_summary(self):
        total = self.total_count
        done = self.success_count + self.fail_count
        percent_total = int(done / total * 100) if total else 0
        if self.has_started:
            self.overall_progress.setVisible(True)
            self.overall_progress.setValue(percent_total)
            self.overall_progress.setFormat(f"{percent_total}%")
        else:
            self.overall_progress.setVisible(False)
        self.summary_label.setText(
            f"完成 {done} / {total}　成功 {self.success_count}　失敗 {self.fail_count}"
        )

    def clear_widgets(self):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)
        self.product_widgets.clear()

    def remove_widget(self, pname):
        widget = self.product_widgets.get(pname)
        if widget:
            self.grid_layout.removeWidget(widget)
            widget.setParent(None)
            del self.product_widgets[pname]
            self.re_layout_grid()

    def refresh_widgets(self):
        self.clear_widgets()
        show_list = [k for k, v in self.product_status.items() if v["status"] in ["running", "fail"]]
        for pname in show_list:
            widget = ProductProgressItem(pname, self.show_log_dialog)
            self.product_status[pname]["widget"] = widget
            self.product_widgets[pname] = widget
        self.re_layout_grid()

    def re_layout_grid(self):
        items = list(self.product_widgets.values())
        if not items:
            return
        w = self.width()
        card_width = 400
        grid_w = max(1, w // (card_width + 28))
        if grid_w < 1:
            grid_w = 1
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
        for idx, wgt in enumerate(items):
            row = idx // grid_w
            col = idx % grid_w
            self.grid_layout.addWidget(wgt, row, col)

    def resizeEvent(self, event):
        self.re_layout_grid()
        return super().resizeEvent(event)

    def toggle_pause_resume(self):
        if not self.bv_batch_uploader:
            return
        if not self.is_paused:
            self.bv_batch_uploader.pause()
            self.pause_resume_btn.setText("繼續")
            self.is_paused = True
            self.summary_label.setText("🚦 已暫停，可以按『繼續』再恢復批次上架。")
        else:
            self.bv_batch_uploader.resume()
            self.pause_resume_btn.setText("暫停")
            self.is_paused = False
            self.summary_label.setText("⏳ 批次上架繼續進行中...")

    def on_paused(self):
        self.pause_resume_btn.setText("繼續")
        self.is_paused = True
        self.summary_label.setText("🚦 已暫停，可以按『繼續』再恢復批次上架。")

    def on_resumed(self):
        self.pause_resume_btn.setText("暫停")
        self.is_paused = False
        self.summary_label.setText("⏳ 批次上架繼續進行中...")

    def retry_failed_uploads(self):
        src_dir = self.dir_edit.text()
        username = self.username_edit.text()
        password = self.password_edit.text()
        threads = self.threads_spin.value()
        domain = self.domain_edit.text().strip()
        headless = self.headless_checkbox.isChecked()
        behavior_mode = self.get_behavior_mode()
        self.summary_label.setText("重跑失敗商品中...")
        if not os.path.isdir(src_dir):
            self.summary_label.setText("來源資料夾不存在")
            return
        if not domain:
            self.summary_label.setText("請輸入主網域")
            return
        if not os.path.exists(FAILED_LIST_FILE):
            self.summary_label.setText("沒有失敗商品可重跑")
            return
        with open(FAILED_LIST_FILE, "r", encoding="utf-8") as f:
            failed = json.load(f)
        product_dirs = []
        for name in failed:
            pdir = os.path.join(src_dir, name)
            if os.path.isdir(pdir) and \
               os.path.exists(os.path.join(pdir, "product_info.json")) and \
               os.path.exists(os.path.join(pdir, "product_output.json")):
                product_dirs.append(pdir)
        if not product_dirs:
            self.summary_label.setText("失敗商品資料夾不存在或檔案不齊全")
            return
        self.total_count = len(product_dirs)
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.product_status = {}
        self.clear_widgets()
        self.has_started = True
        self.overall_progress.setVisible(True)
        self.pause_resume_btn.setEnabled(True)
        self.pause_resume_btn.setText("暫停")
        for p in product_dirs:
            pname = os.path.basename(p)
            self.product_status[pname] = {
                "status": "waiting", "progress": 0, "log": "", "widget": None
            }
        self.update_summary()
        self.refresh_widgets()
        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            only_failed=failed,
            behavior_mode=behavior_mode,
            speed_status_callback=None,
            round_status_callback=None
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)
        self.bv_batch_uploader.paused_signal.connect(self.on_paused)
        self.bv_batch_uploader.resumed_signal.connect(self.on_resumed)
        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        self.is_paused = False

    def save_failed_list(self, fail_list):
        failed = [item[0] for item in fail_list]
        with open(FAILED_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BVShopMainWindow()
    win.show()
    sys.exit(app.exec_())
