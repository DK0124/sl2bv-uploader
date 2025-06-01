import sys
import os
import json
import time
import psutil
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QSpinBox, QGridLayout, QScrollArea, QProgressBar, QTextEdit, QFrame, QCheckBox, QComboBox
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

from batch_uploader import BVShopBatchUploader
from speed_controller import BehaviorMode

CONFIG_FILE = "config.json"

def suggest_max_workers():
    cpu = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total // (1024 ** 3)
    max_by_ram = max(1, int(ram_gb * 0.85 // 0.45))
    max_safe = min(cpu * 2, max_by_ram)
    return min(max_safe, 16)

class ProductProgressItem(QWidget):
    def __init__(self, name):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        self.name_label = QLabel(name, self)
        self.name_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("margin-bottom: 2px; color: #ffd600;")
        layout.addWidget(self.name_label, stretch=0)

        stat_hbox = QHBoxLayout()
        stat_hbox.setSpacing(8)
        self.status_icon = QLabel("⏳", self)
        self.status_icon.setFixedWidth(24)
        self.status_icon.setAlignment(Qt.AlignCenter)
        stat_hbox.addWidget(self.status_icon)
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stat_hbox.addWidget(self.status_label)
        layout.addLayout(stat_hbox, stretch=0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                background: #202428;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffe066, stop:1 #ffb400
                );
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar, stretch=0)

        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(38)
        self.log_edit.setStyleSheet("font-size:0.93em; color:#ccc; background:#23272b; border-radius:4px;")
        layout.addWidget(self.log_edit, stretch=1)

        self.setStyleSheet("""
            QWidget#ProductProgressItem {
                border: none;
                border-radius: 8px;
                background: #191c20;
            }
        """)
        self.setObjectName("ProductProgressItem")
        self.setLayout(layout)

    def update_progress(self, percent, detail_log):
        self.progress_bar.setValue(percent)
        if detail_log:
            self.log_edit.append(detail_log)

    def set_status(self, success, elapsed, detail_log):
        if success is None:
            self.status_icon.setText("⏳")
            self.status_label.setText("")
            self.setStyleSheet("border: none; border-radius: 8px; background: #191c20;")
        elif success:
            self.status_icon.setText("✅")
            self.status_label.setText(f"<span style='color:#57e690'>上架完成</span>")
            self.setStyleSheet("border: none; border-radius: 8px; background: #202428;")
        else:
            self.status_icon.setText("❌")
            self.status_label.setText("<span style='color:#ff4444'>上架失敗</span>")
            self.setStyleSheet("border: none; border-radius: 8px; background: #231c1c;")
        if detail_log:
            self.log_edit.append(detail_log)

class BVShopMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BVShop 批次上架監控矩陣")
        self.resize(1280, 820)
        self.init_ui()
        self.bv_batch_uploader = None
        self.load_config()
        self.product_status = {}   # 所有商品狀態資料
        self.product_widgets = {}  # 只存畫面上有顯示的 widget
        self.total_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(18, 14, 18, 14)

        ctl_wrap = QFrame()
        ctl_wrap.setFrameShape(QFrame.StyledPanel)
        ctl_wrap.setStyleSheet("background: #21252a; border-radius: 12px; border:none;")
        ctl_layout = QVBoxLayout()
        ctl_layout.setSpacing(6)
        ctl_layout.setContentsMargins(12, 8, 12, 8)

        row1 = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("來源資料夾")
        self.dir_btn = QPushButton("選擇")
        self.dir_btn.clicked.connect(self.choose_dir)
        row1.addWidget(QLabel("來源資料夾:"))
        row1.addWidget(self.dir_edit, 2)
        row1.addWidget(self.dir_btn)
        ctl_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("帳號")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密碼")
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
        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("前台主網域（如 https://gd.bvshop.tw）")
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
        row4.addWidget(self.headless_checkbox)
        row4.addWidget(QLabel("上架速度模式:"))
        row4.addWidget(self.behavior_mode_combo)
        ctl_layout.addLayout(row4)

        ctl_wrap.setLayout(ctl_layout)
        main_layout.addWidget(ctl_wrap)

        self.summary_label = QLabel("尚未開始")
        self.summary_label.setStyleSheet("font-size: 1.10em; font-weight:bold; margin-bottom:6px;")
        main_layout.addWidget(self.summary_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("尚未開始")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                height: 28px;
                border: none;
                border-radius: 8px;
                background: #23272b;
                text-align: center;
                font-size: 1.10em;
                font-weight: bold;
                color: #222;
                margin: 10px 60px 6px 60px;
                min-width: 420px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe066, stop:1 #ffb400);
                border-radius: 8px;
            }
        """)
        main_layout.addWidget(self.overall_progress, alignment=Qt.AlignHCenter)

        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(12)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        grid_container.setLayout(self.grid_layout)
        self.grid_area.setWidget(grid_container)
        main_layout.addWidget(self.grid_area, stretch=1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始批次上架")
        self.stop_btn = QPushButton("終止")
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.start_btn.clicked.connect(self.start_batch_upload)
        self.stop_btn.clicked.connect(self.stop_batch_upload)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self.update_time_estimate)
        self.setMinimumSize(960, 700)
        self.setStyleSheet('''
            QWidget { background: #181c20; color: #fff; font-family: 'Segoe UI', 'Arial', '微軟正黑體', sans-serif; font-size: 1.07em; border:none; }
            QPushButton { background-color: #23272b; color: #fff; border: none; border-radius: 6px; padding: 8px 18px; font-size: 1em;}
            QPushButton:hover { background-color: #2e3238; }
            QLineEdit, QSpinBox { background-color: #23272b; color: #ffffff; border: none; border-radius: 4px; font-size: 1em; }
            QLabel { color: #ffffff; font-size: 1em; }
            QScrollArea { border: none; }
            QFrame { border:none; }
        ''')

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

        for p in product_dirs:
            pname = os.path.basename(p)
            self.product_status[pname] = {
                "status": "pending", "progress": 0, "log": "", "widget": None
            }
        self.update_summary()
        # 只加載進行中/失敗的商品
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

        import threading
        def runner():
            self.bv_batch_uploader.batch_upload()
        threading.Thread(target=runner, daemon=True).start()
        self.estimate_timer.start(1000)
        self.update_time_estimate()

    def update_product_progress(self, product_name, percent, success, elapsed, detail_log):
        status = self.product_status.get(product_name)
        if not status:
            return
        status["progress"] = percent
        if detail_log:
            status["log"] = (status["log"] + "\n" + detail_log).strip()
        if success is None:
            status["status"] = "pending"
        elif success:
            status["status"] = "success"
            self.success_count += 1
        else:
            status["status"] = "fail"
            self.fail_count += 1

        # 僅顯示「進行中」和「失敗」的商品
        if status["status"] in ["pending", "fail"]:
            if not status.get("widget"):
                status["widget"] = ProductProgressItem(product_name)
                self.product_widgets[product_name] = status["widget"]
                self.re_layout_grid()
            status["widget"].update_progress(percent, detail_log)
            status["widget"].set_status(success, elapsed, detail_log)
        else:  # success時移除
            if status.get("widget"):
                self.remove_widget(product_name)
                status["widget"] = None

        self.update_summary()

    def batch_all_done(self, total, success, fail, fail_list):
        self.estimate_timer.stop()
        elapsed = int(time.time() - self.start_time)
        self.overall_progress.setValue(100)
        self.overall_progress.setFormat("100% 已完成")
        self.summary_label.setText(
            f"全部完成：成功 {success}/{total}，失敗 {fail}　總花費 {elapsed // 60}分{elapsed % 60}秒"
        )

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
        self.overall_progress.setValue(percent_total)
        self.overall_progress.setFormat(f"{percent_total}%")
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
        show_list = [k for k, v in self.product_status.items() if v["status"] in ["pending", "fail"]]
        for pname in show_list:
            widget = ProductProgressItem(pname)
            self.product_status[pname]["widget"] = widget
            self.product_widgets[pname] = widget
        self.re_layout_grid()

    def re_layout_grid(self):
        items = list(self.product_widgets.values())
        if not items:
            return
        w = self.grid_area.viewport().width()
        grid_w = max(1, w // 340)
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

    def stop_batch_upload(self):
        if self.bv_batch_uploader:
            self.bv_batch_uploader.stop()
            self.estimate_timer.stop()
            self.summary_label.setText("⚠️ 已強制終止所有上架任務")
            self.overall_progress.setFormat("已終止")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BVShopMainWindow()
    win.show()
    sys.exit(app.exec_())
