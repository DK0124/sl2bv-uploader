import sys
import os
import json
import time
import psutil
import sys
import os
import json
import time
import psutil
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QSpinBox, QGridLayout, QSizePolicy, QScrollArea, QProgressBar, QTextEdit, QFrame, QCheckBox, QComboBox
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

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

class ExpandableLogBox(QWidget):
    def __init__(self, log_text="", parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.toggle_btn = QPushButton("展開log", self)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.clicked.connect(self.toggle)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(80)
        self.layout.addWidget(self.toggle_btn)
        self.layout.addWidget(self.log_edit)
        self.setLayout(self.layout)
        self.toggle()

    def append_log(self, log_text):
        if not log_text:
            return
        current = self.log_edit.toPlainText()
        if current and not current.endswith('\n'):
            current += '\n'
        self.log_edit.setPlainText(current + log_text)
        self.log_edit.moveCursor(self.log_edit.textCursor().End)

    def set_log(self, log_text):
        self.log_edit.setPlainText(log_text)

    def toggle(self):
        if self.toggle_btn.isChecked():
            self.log_edit.show()
            self.toggle_btn.setText("收合log")
        else:
            self.log_edit.hide()
            self.toggle_btn.setText("展開log")

class ProductProgressItem(QWidget):
    def __init__(self, name):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        self.name_label = QLabel(name, self)
        self.name_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("margin-bottom: 4px; color: #ffd600;")
        layout.addWidget(self.name_label, stretch=0)

        stat_hbox = QHBoxLayout()
        stat_hbox.setSpacing(12)
        stat_hbox.setContentsMargins(0, 0, 0, 0)
        self.status_icon = QLabel("⏳", self)
        self.status_icon.setFixedWidth(36)
        self.status_icon.setAlignment(Qt.AlignCenter)
        stat_hbox.addWidget(self.status_icon)
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stat_hbox.addWidget(self.status_label)
        layout.addLayout(stat_hbox, stretch=0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 9px;
                text-align: center;
                font-weight: bold;
                background: #202428;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffe066, stop:1 #ffb400
                );
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.progress_bar, stretch=0)

        self.logbox = ExpandableLogBox("", self)
        self.logbox.setStyleSheet("margin-top: 2px; border:none;")
        layout.addWidget(self.logbox, stretch=1)

        self.setStyleSheet("""
            QWidget#ProductProgressItem {
                border: none;
                border-radius: 12px;
                background: #191c20;
            }
        """)
        self.setObjectName("ProductProgressItem")

        self.setLayout(layout)

    def update_progress(self, percent, detail_log):
        self.progress_bar.setValue(percent)
        if detail_log:
            self.logbox.append_log(detail_log)

    def set_status(self, success, elapsed, detail_log):
        if success is None:
            self.status_icon.setText("⏳")
            self.status_label.setText("")
            self.setStyleSheet("border: none; border-radius: 12px; background: #191c20;")
        elif success:
            self.status_icon.setText("✅")
            self.status_label.setText(f"<span style='color:#57e690'>上架完成</span>")
            self.setStyleSheet("border: none; border-radius: 12px; background: #202428;")
        else:
            self.status_icon.setText("❌")
            self.status_label.setText("<span style='color:#ff4444'>上架失敗</span>")
            self.setStyleSheet("border: none; border-radius: 12px; background: #231c1c;")
        if detail_log:
            self.logbox.append_log(detail_log)

class BVShopMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BVShop 批次上架監控儀表板")
        self.resize(1260, 800)
        self.init_ui()
        self.bv_batch_uploader = None
        self.load_config()
        self.product_widgets = {}
        self.start_time = None
        self.timeout_error_count = 0
        self.timeout_ban_threshold = 4
        self.last_timeout_check_idx = -1
        self._speed_status = "自動"
        self._last_behavior_mode = BehaviorMode.AUTO
        self._current_round = 1
        self._max_retries = 5

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(18, 14, 18, 14)

        ctl_wrap = QFrame()
        ctl_wrap.setFrameShape(QFrame.StyledPanel)
        ctl_wrap.setStyleSheet("background: #21252a; border-radius: 12px; border:none;")
        ctl_layout = QHBoxLayout()
        ctl_layout.setSpacing(18)
        ctl_layout.setContentsMargins(18, 8, 18, 8)

        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("來源資料夾")
        self.dir_btn = QPushButton("選擇")
        self.dir_btn.clicked.connect(self.choose_dir)
        ctl_layout.addWidget(QLabel("來源資料夾:"))
        ctl_layout.addWidget(self.dir_edit, 2)
        ctl_layout.addWidget(self.dir_btn)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("帳號")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密碼")
        ctl_layout.addWidget(QLabel("帳號:"))
        ctl_layout.addWidget(self.username_edit, 1)
        ctl_layout.addWidget(QLabel("密碼:"))
        ctl_layout.addWidget(self.password_edit, 1)

        self.threads_spin = QSpinBox()
        self.threads_spin.setMinimum(1)
        self.suggested_workers = suggest_max_workers()
        self.threads_spin.setMaximum(9999)
        self.threads_spin.setValue(self.suggested_workers)
        ctl_layout.addWidget(QLabel("同時上架數:"))
        ctl_layout.addWidget(self.threads_spin)

        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("前台主網域（如 https://gd.bvshop.tw）")
        ctl_layout.addWidget(QLabel("主網域:"))
        ctl_layout.addWidget(self.domain_edit, 2)

        self.headless_checkbox = QCheckBox("無頭瀏覽器(效能較佳)")
        self.headless_checkbox.setChecked(True)
        ctl_layout.addWidget(self.headless_checkbox)

        self.behavior_mode_combo = QComboBox()
        self.behavior_mode_combo.addItems(["自動（建議）", "極速", "安全"])
        ctl_layout.addWidget(QLabel("上架速度模式:"))
        ctl_layout.addWidget(self.behavior_mode_combo)

        ctl_wrap.setLayout(ctl_layout)
        main_layout.addWidget(ctl_wrap)

        self.suggest_label = QLabel()
        self.suggest_label.setStyleSheet("color:#ffb400; margin-bottom:6px; font-size:0.97em;")
        main_layout.addWidget(self.suggest_label)
        self.update_suggest_label()
        self.threads_spin.valueChanged.connect(self.update_suggest_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("尚未開始")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                height: 36px;
                border: none;
                border-radius: 12px;
                background: #23272b;
                text-align: center;
                font-size: 1.2em;
                font-weight: bold;
                color: #222;
                margin: 14px 60px 8px 60px;
                min-width: 680px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe066, stop:1 #ffb400);
                border-radius: 10px;
            }
        """)
        main_layout.addWidget(self.overall_progress, alignment=Qt.AlignHCenter)

        self.summary_label = QLabel("尚未開始")
        self.summary_label.setStyleSheet("font-size: 1.10em; font-weight:bold; margin-bottom:8px;")
        main_layout.addWidget(self.summary_label)

        self.speed_status_label = QLabel("目前運行速度：自動　|　目前第 1 / 5 輪")
        self.speed_status_label.setStyleSheet("font-size:1em; color:#80f0d0; margin-bottom:8px;")
        main_layout.addWidget(self.speed_status_label)

        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(20, 16, 20, 16)
        grid_container.setLayout(self.grid_layout)
        self.grid_area.setWidget(grid_container)
        main_layout.addWidget(self.grid_area, stretch=1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始批次上架")
        self.pause_btn = QPushButton("暫停")
        self.resume_btn = QPushButton("恢復")
        self.stop_btn = QPushButton("終止")
        self.retry_failed_btn = QPushButton("重跑失敗商品")
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.retry_failed_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.start_btn.clicked.connect(self.start_batch_upload)
        self.pause_btn.clicked.connect(self.pause_batch_upload)
        self.resume_btn.clicked.connect(self.resume_batch_upload)
        self.stop_btn.clicked.connect(self.stop_batch_upload)
        self.retry_failed_btn.clicked.connect(self.retry_failed_uploads)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self.update_time_estimate)
        self.setMinimumSize(940, 650)
        self.setStyleSheet('''
            QWidget { background: #181c20; color: #fff; font-family: 'Segoe UI', 'Arial', '微軟正黑體', sans-serif; font-size: 1.07em; border:none; }
            QPushButton { background-color: #23272b; color: #fff; border: none; border-radius: 6px; padding: 8px 18px; font-size: 1em; min-height: 34px; }
            QPushButton:hover { background-color: #2e3238; }
            QLineEdit, QSpinBox { background-color: #23272b; color: #ffffff; border: none; border-radius: 4px; font-size: 1em; }
            QLabel { color: #ffffff; font-size: 1em; }
            QScrollArea { border: none; }
            QFrame { border:none; }
        ''')

    def update_suggest_label(self):
        val = self.threads_spin.value()
        tip = f"建議同時上架數為 {self.suggested_workers}（依本機資源自動計算，CPU: {os.cpu_count()}核, RAM: {psutil.virtual_memory().total // (1024 ** 3)}GB）。"
        if val > self.suggested_workers:
            tip += " ⚠️ 設定過多容易導致失敗、timeout、被ban，建議不要超過建議值。"
            self.suggest_label.setStyleSheet("color:#ff4444; margin-bottom:6px; font-size:1.01em; font-weight:bold;")
        else:
            self.suggest_label.setStyleSheet("color:#ffb400; margin-bottom:6px; font-size:0.97em;")
        self.suggest_label.setText(tip)

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
        self._current_round = 1
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
        self.finished_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.timeout_error_count = 0
        self.last_timeout_check_idx = -1

        self.product_widgets = {}
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)

        for p in product_dirs:
            pname = os.path.basename(p)
            widget = ProductProgressItem(pname)
            self.product_widgets[pname] = widget
        self.re_layout_grid()

        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            behavior_mode=behavior_mode,
            speed_status_callback=self.update_speed_status,
            round_status_callback=self.update_round_status
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)

        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        self.update_speed_status("自動")
        self.update_round_status(1, self._max_retries)

    def update_speed_status(self, mode_str):
        self._speed_status = mode_str
        self.speed_status_label.setText(f"目前運行速度：{self._speed_status}　|　目前第 {self._current_round} / {self._max_retries} 輪")

    def update_round_status(self, current_round, max_retries):
        self._current_round = current_round
        self._max_retries = max_retries
        self.speed_status_label.setText(f"目前運行速度：{self._speed_status}　|　目前第 {self._current_round} / {self._max_retries} 輪")

    def update_product_progress(self, product_name, percent, success, elapsed, detail_log):
        widget = self.product_widgets.get(product_name)
        if not widget:
            return
        widget.update_progress(percent, detail_log)
        if success is not None:
            widget.set_status(success, elapsed, detail_log)
            self.finished_count = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
            self.success_count = sum(1 for w in self.product_widgets.values() if w.status_icon.text() == "✅")
            self.fail_count = sum(1 for w in self.product_widgets.values() if w.status_icon.text() == "❌")
            if success is False:
                self.save_failed_product(product_name)
        total = self.total_count
        done = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
        percent_total = int(done / total * 100) if total else 0
        self.overall_progress.setValue(percent_total)
        self.overall_progress.setFormat(f"{percent_total}%")
        self.summary_label.setText(
            f"完成 {done} / {total}　成功 {self.success_count}　失敗 {self.fail_count}"
        )

    def update_time_estimate(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        done = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
        total = self.total_count
        if done > 0 and total > done:
            avg = elapsed / done
            remaining = total - done
            left = int(avg * remaining)
            self.summary_label.setText(
                f"{self.summary_label.text()}　預估剩餘 {left // 60}分{left % 60}秒"
            )

    def batch_all_done(self, total, success, fail, fail_list):
        self.estimate_timer.stop()
        elapsed = int(time.time() - self.start_time)
        self.overall_progress.setValue(100)
        self.overall_progress.setFormat("100% 已完成")
        self.summary_label.setText(
            f"全部完成：成功 {success}/{total}，失敗 {fail}　總花費 {elapsed // 60}分{elapsed % 60}秒"
        )
        self.save_failed_list(fail_list)

    def pause_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.pause()

    def resume_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.resume()

    def stop_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.stop()
            self.estimate_timer.stop()
            self.summary_label.setText("⚠️ 已強制終止所有上架任務")
            self.overall_progress.setFormat("已終止")

    def save_failed_product(self, pname):
        failed = []
        if os.path.exists(FAILED_LIST_FILE):
            try:
                with open(FAILED_LIST_FILE, "r", encoding="utf-8") as f:
                    failed = json.load(f)
            except Exception:
                failed = []
        if pname not in failed:
            failed.append(pname)
            with open(FAILED_LIST_FILE, "w", encoding="utf-8") as f:
                json.dump(failed, f, ensure_ascii=False, indent=2)

    def save_failed_list(self, fail_list):
        failed = [item[0] for item in fail_list]
        with open(FAILED_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)

    def retry_failed_uploads(self):
        src_dir = self.dir_edit.text()
        username = self.username_edit.text()
        password = self.password_edit.text()
        threads = self.threads_spin.value()
        domain = self.domain_edit.text().strip()
        headless = self.headless_checkbox.isChecked()
        behavior_mode = self.get_behavior_mode()
        self._current_round = 1
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
        self.finished_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.timeout_error_count = 0
        self.last_timeout_check_idx = -1
        self.product_widgets = {}
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)
        for p in product_dirs:
            pname = os.path.basename(p)
            widget = ProductProgressItem(pname)
            self.product_widgets[pname] = widget
        self.re_layout_grid()
        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            only_failed=failed,
            behavior_mode=behavior_mode,
            speed_status_callback=self.update_speed_status,
            round_status_callback=self.update_round_status
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)
        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        self.update_speed_status("自動")
        self.update_round_status(1, self._max_retries)

    def re_layout_grid(self):
        items = list(self.product_widgets.values())
        if not items:
            return
        w = self.grid_area.viewport().width()
        grid_w = max(1, w // 420)
        if grid_w < 1:
            grid_w = 1
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)
        for idx, wgt in enumerate(items):
            row = idx // grid_w
            col = idx % grid_w
            self.grid_layout.addWidget(wgt, row, col)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BVShopMainWindow()
    win.show()
    sys.exit(app.exec_())
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QSpinBox, QGridLayout, QSizePolicy, QScrollArea, QProgressBar, QTextEdit, QFrame, QCheckBox, QComboBox
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

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

class ExpandableLogBox(QWidget):
    def __init__(self, log_text="", parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.toggle_btn = QPushButton("展開log", self)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.clicked.connect(self.toggle)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(80)
        self.layout.addWidget(self.toggle_btn)
        self.layout.addWidget(self.log_edit)
        self.setLayout(self.layout)
        self.toggle()

    def append_log(self, log_text):
        if not log_text:
            return
        current = self.log_edit.toPlainText()
        if current and not current.endswith('\n'):
            current += '\n'
        self.log_edit.setPlainText(current + log_text)
        self.log_edit.moveCursor(self.log_edit.textCursor().End)

    def set_log(self, log_text):
        self.log_edit.setPlainText(log_text)

    def toggle(self):
        if self.toggle_btn.isChecked():
            self.log_edit.show()
            self.toggle_btn.setText("收合log")
        else:
            self.log_edit.hide()
            self.toggle_btn.setText("展開log")

class ProductProgressItem(QWidget):
    def __init__(self, name):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        self.name_label = QLabel(name, self)
        self.name_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("margin-bottom: 4px; color: #ffd600;")
        layout.addWidget(self.name_label, stretch=0)

        stat_hbox = QHBoxLayout()
        stat_hbox.setSpacing(12)
        stat_hbox.setContentsMargins(0, 0, 0, 0)
        self.status_icon = QLabel("⏳", self)
        self.status_icon.setFixedWidth(36)
        self.status_icon.setAlignment(Qt.AlignCenter)
        stat_hbox.addWidget(self.status_icon)
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stat_hbox.addWidget(self.status_label)
        layout.addLayout(stat_hbox, stretch=0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 9px;
                text-align: center;
                font-weight: bold;
                background: #202428;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffe066, stop:1 #ffb400
                );
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.progress_bar, stretch=0)

        self.logbox = ExpandableLogBox("", self)
        self.logbox.setStyleSheet("margin-top: 2px; border:none;")
        layout.addWidget(self.logbox, stretch=1)

        self.setStyleSheet("""
            QWidget#ProductProgressItem {
                border: none;
                border-radius: 12px;
                background: #191c20;
            }
        """)
        self.setObjectName("ProductProgressItem")

        self.setLayout(layout)

    def update_progress(self, percent, detail_log):
        self.progress_bar.setValue(percent)
        if detail_log:
            self.logbox.append_log(detail_log)

    def set_status(self, success, elapsed, detail_log):
        if success is None:
            self.status_icon.setText("⏳")
            self.status_label.setText("")
            self.setStyleSheet("border: none; border-radius: 12px; background: #191c20;")
        elif success:
            self.status_icon.setText("✅")
            self.status_label.setText(f"<span style='color:#57e690'>上架完成</span>")
            self.setStyleSheet("border: none; border-radius: 12px; background: #202428;")
        else:
            self.status_icon.setText("❌")
            self.status_label.setText("<span style='color:#ff4444'>上架失敗</span>")
            self.setStyleSheet("border: none; border-radius: 12px; background: #231c1c;")
        if detail_log:
            self.logbox.append_log(detail_log)

class BVShopMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BVShop 批次上架監控儀表板")
        self.resize(1260, 800)
        self.init_ui()
        self.bv_batch_uploader = None
        self.load_config()
        self.product_widgets = {}
        self.start_time = None
        self.timeout_error_count = 0
        self.timeout_ban_threshold = 4
        self.last_timeout_check_idx = -1
        self._speed_status = "自動"
        self._last_behavior_mode = BehaviorMode.AUTO

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(18, 14, 18, 14)

        ctl_wrap = QFrame()
        ctl_wrap.setFrameShape(QFrame.StyledPanel)
        ctl_wrap.setStyleSheet("background: #21252a; border-radius: 12px; border:none;")
        ctl_layout = QHBoxLayout()
        ctl_layout.setSpacing(18)
        ctl_layout.setContentsMargins(18, 8, 18, 8)

        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("來源資料夾")
        self.dir_btn = QPushButton("選擇")
        self.dir_btn.clicked.connect(self.choose_dir)
        ctl_layout.addWidget(QLabel("來源資料夾:"))
        ctl_layout.addWidget(self.dir_edit, 2)
        ctl_layout.addWidget(self.dir_btn)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("帳號")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密碼")
        ctl_layout.addWidget(QLabel("帳號:"))
        ctl_layout.addWidget(self.username_edit, 1)
        ctl_layout.addWidget(QLabel("密碼:"))
        ctl_layout.addWidget(self.password_edit, 1)

        self.threads_spin = QSpinBox()
        self.threads_spin.setMinimum(1)
        self.suggested_workers = suggest_max_workers()
        self.threads_spin.setMaximum(9999)
        self.threads_spin.setValue(self.suggested_workers)
        ctl_layout.addWidget(QLabel("同時上架數:"))
        ctl_layout.addWidget(self.threads_spin)

        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("前台主網域（如 https://gd.bvshop.tw）")
        ctl_layout.addWidget(QLabel("主網域:"))
        ctl_layout.addWidget(self.domain_edit, 2)

        self.headless_checkbox = QCheckBox("無頭瀏覽器(效能較佳)")
        self.headless_checkbox.setChecked(True)
        ctl_layout.addWidget(self.headless_checkbox)

        # 新增：行為模式選單
        self.behavior_mode_combo = QComboBox()
        self.behavior_mode_combo.addItems(["自動（建議）", "極速", "安全"])
        ctl_layout.addWidget(QLabel("上架速度模式:"))
        ctl_layout.addWidget(self.behavior_mode_combo)

        ctl_wrap.setLayout(ctl_layout)
        main_layout.addWidget(ctl_wrap)

        self.suggest_label = QLabel()
        self.suggest_label.setStyleSheet("color:#ffb400; margin-bottom:6px; font-size:0.97em;")
        main_layout.addWidget(self.suggest_label)
        self.update_suggest_label()
        self.threads_spin.valueChanged.connect(self.update_suggest_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("尚未開始")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                height: 36px;
                border: none;
                border-radius: 12px;
                background: #23272b;
                text-align: center;
                font-size: 1.2em;
                font-weight: bold;
                color: #222;
                margin: 14px 60px 8px 60px;
                min-width: 680px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe066, stop:1 #ffb400);
                border-radius: 10px;
            }
        """)
        main_layout.addWidget(self.overall_progress, alignment=Qt.AlignHCenter)

        self.summary_label = QLabel("尚未開始")
        self.summary_label.setStyleSheet("font-size: 1.10em; font-weight:bold; margin-bottom:8px;")
        main_layout.addWidget(self.summary_label)

        # 新增：目前運行速度狀態
        self.speed_status_label = QLabel("目前運行速度：自動")
        self.speed_status_label.setStyleSheet("font-size:1em; color:#80f0d0; margin-bottom:8px;")
        main_layout.addWidget(self.speed_status_label)

        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(20, 16, 20, 16)
        grid_container.setLayout(self.grid_layout)
        self.grid_area.setWidget(grid_container)
        main_layout.addWidget(self.grid_area, stretch=1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始批次上架")
        self.pause_btn = QPushButton("暫停")
        self.resume_btn = QPushButton("恢復")
        self.stop_btn = QPushButton("終止")
        self.retry_failed_btn = QPushButton("重跑失敗商品")
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.retry_failed_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.start_btn.clicked.connect(self.start_batch_upload)
        self.pause_btn.clicked.connect(self.pause_batch_upload)
        self.resume_btn.clicked.connect(self.resume_batch_upload)
        self.stop_btn.clicked.connect(self.stop_batch_upload)
        self.retry_failed_btn.clicked.connect(self.retry_failed_uploads)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self.update_time_estimate)
        self.setMinimumSize(940, 650)
        self.setStyleSheet('''
            QWidget { background: #181c20; color: #fff; font-family: 'Segoe UI', 'Arial', '微軟正黑體', sans-serif; font-size: 1.07em; border:none; }
            QPushButton { background-color: #23272b; color: #fff; border: none; border-radius: 6px; padding: 8px 18px; font-size: 1em; min-height: 34px; }
            QPushButton:hover { background-color: #2e3238; }
            QLineEdit, QSpinBox { background-color: #23272b; color: #ffffff; border: none; border-radius: 4px; font-size: 1em; }
            QLabel { color: #ffffff; font-size: 1em; }
            QScrollArea { border: none; }
            QFrame { border:none; }
        ''')

    def update_suggest_label(self):
        val = self.threads_spin.value()
        tip = f"建議同時上架數為 {self.suggested_workers}（依本機資源自動計算，CPU: {os.cpu_count()}核, RAM: {psutil.virtual_memory().total // (1024 ** 3)}GB）。"
        if val > self.suggested_workers:
            tip += " ⚠️ 設定過多容易導致失敗、timeout、被ban，建議不要超過建議值。"
            self.suggest_label.setStyleSheet("color:#ff4444; margin-bottom:6px; font-size:1.01em; font-weight:bold;")
        else:
            self.suggest_label.setStyleSheet("color:#ffb400; margin-bottom:6px; font-size:0.97em;")
        self.suggest_label.setText(tip)

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
        self.finished_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.timeout_error_count = 0
        self.last_timeout_check_idx = -1

        self.product_widgets = {}
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)

        for p in product_dirs:
            pname = os.path.basename(p)
            widget = ProductProgressItem(pname)
            self.product_widgets[pname] = widget
        self.re_layout_grid()

        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            behavior_mode=behavior_mode,
            speed_status_callback=self.update_speed_status
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)

        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        # 初始化速度模式顯示
        self.update_speed_status("自動")

    def update_speed_status(self, mode_str):
        self.speed_status_label.setText(f"目前運行速度：{mode_str}")

    def update_product_progress(self, product_name, percent, success, elapsed, detail_log):
        widget = self.product_widgets.get(product_name)
        if not widget:
            return
        widget.update_progress(percent, detail_log)
        if success is not None:
            widget.set_status(success, elapsed, detail_log)
            self.finished_count = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
            self.success_count = sum(1 for w in self.product_widgets.values() if w.status_icon.text() == "✅")
            self.fail_count = sum(1 for w in self.product_widgets.values() if w.status_icon.text() == "❌")
            # 記錄失敗商品
            if success is False:
                self.save_failed_product(product_name)
        total = self.total_count
        done = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
        percent_total = int(done / total * 100) if total else 0
        self.overall_progress.setValue(percent_total)
        self.overall_progress.setFormat(f"{percent_total}%")
        self.summary_label.setText(
            f"完成 {done} / {total}　成功 {self.success_count}　失敗 {self.fail_count}"
        )

    def update_time_estimate(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        done = sum(1 for w in self.product_widgets.values() if w.progress_bar.value() == 100)
        total = self.total_count
        if done > 0 and total > done:
            avg = elapsed / done
            remaining = total - done
            left = int(avg * remaining)
            self.summary_label.setText(
                f"{self.summary_label.text()}　預估剩餘 {left // 60}分{left % 60}秒"
            )

    def batch_all_done(self, total, success, fail, fail_list):
        self.estimate_timer.stop()
        elapsed = int(time.time() - self.start_time)
        self.overall_progress.setValue(100)
        self.overall_progress.setFormat("100% 已完成")
        self.summary_label.setText(
            f"全部完成：成功 {success}/{total}，失敗 {fail}　總花費 {elapsed // 60}分{elapsed % 60}秒"
        )
        self.save_failed_list(fail_list)

    def pause_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.pause()

    def resume_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.resume()

    def stop_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.stop()
            self.estimate_timer.stop()
            self.summary_label.setText("⚠️ 已強制終止所有上架任務")
            self.overall_progress.setFormat("已終止")

    def save_failed_product(self, pname):
        failed = []
        if os.path.exists(FAILED_LIST_FILE):
            try:
                with open(FAILED_LIST_FILE, "r", encoding="utf-8") as f:
                    failed = json.load(f)
            except Exception:
                failed = []
        if pname not in failed:
            failed.append(pname)
            with open(FAILED_LIST_FILE, "w", encoding="utf-8") as f:
                json.dump(failed, f, ensure_ascii=False, indent=2)

    def save_failed_list(self, fail_list):
        failed = [item[0] for item in fail_list]
        with open(FAILED_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)

    def retry_failed_uploads(self):
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
        self.finished_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()
        self.timeout_error_count = 0
        self.last_timeout_check_idx = -1
        self.product_widgets = {}
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)
        for p in product_dirs:
            pname = os.path.basename(p)
            widget = ProductProgressItem(pname)
            self.product_widgets[pname] = widget
        self.re_layout_grid()
        self.bv_batch_uploader = BVShopBatchUploader(
            src_dir=src_dir,
            username=username,
            password=password,
            max_workers=threads,
            product_domain=domain,
            headless=headless,
            only_failed=failed,
            behavior_mode=behavior_mode,
            speed_status_callback=self.update_speed_status
        )
        self.bv_batch_uploader.product_progress_signal.connect(self.update_product_progress)
        self.bv_batch_uploader.all_done_signal.connect(self.batch_all_done)
        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()
        self.update_speed_status("自動")

    def re_layout_grid(self):
        items = list(self.product_widgets.values())
        if not items:
            return
        w = self.grid_area.viewport().width()
        grid_w = max(1, w // 420)
        if grid_w < 1:
            grid_w = 1
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                wgt = item.widget()
                if wgt:
                    self.grid_layout.removeWidget(wgt)
                    wgt.setParent(None)
        for idx, wgt in enumerate(items):
            row = idx // grid_w
            col = idx % grid_w
            self.grid_layout.addWidget(wgt, row, col)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BVShopMainWindow()
    win.show()
    sys.exit(app.exec_())
