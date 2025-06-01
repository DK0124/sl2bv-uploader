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
        self.resize(850, 560)
        layout = QVBoxLayout(self)
        label = QLabel(title)
        label.setStyleSheet("font-weight:bold;font-size:1.1em;margin-bottom:8px; color:#a9b5c7;")
        layout.addWidget(label)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlainText(log_text)
        self.log_edit.setStyleSheet("""
            background: #22252b;
            border-radius: 18px;
            color: #b8c3d1;
            font-size: 1.07em;
            padding: 14px;
        """)
        layout.addWidget(self.log_edit)
        btn = QPushButton("關閉")
        btn.setStyleSheet("""
            QPushButton {
                background: #2c3140;
                border: none;
                border-radius: 13px;
                padding: 10px 36px;
                font-size: 1.18em;
                color: #8ab4f8;
            }
            QPushButton:hover {
                background: #2d3754;
                color: #a7d0ff;
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
        layout.setSpacing(7)
        layout.setContentsMargins(28, 20, 28, 20)

        self.name_label = QLabel(name, self)
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 商品名稱字體極小且細灰色
        font = QFont("SF Pro Text", 9, QFont.Medium)
        self.name_label.setFont(font)
        self.name_label.setStyleSheet("color:#6d7a8b; margin-bottom: 2px; letter-spacing:0.2px;")
        layout.addWidget(self.name_label, stretch=0)

        stat_hbox = QHBoxLayout()
        stat_hbox.setSpacing(12)
        self.status_icon = QLabel("⏳", self)
        self.status_icon.setFixedWidth(24)
        self.status_icon.setAlignment(Qt.AlignCenter)
        stat_hbox.addWidget(self.status_icon)
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setStyleSheet("font-size:1.09em; color: #b7c9e0; font-weight: 500;")
        stat_hbox.addWidget(self.status_label)
        layout.addLayout(stat_hbox, stretch=0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(30)
        # 進度條色調蘋果藍綠，文字微亮
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 13px;
                text-align: center;
                font-weight: 520;
                background: #21232c;
                color: #bfe1ff;
                font-size: 1.19em;
                letter-spacing:0.3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #53b6ff, stop:0.4 #5edbff, stop:0.8 #6e80ff, stop:1 #4f69c6
                );
                border-radius: 13px;
            }
        """)
        layout.addWidget(self.progress_bar, stretch=0)

        # 點擊整張卡片或進度條皆可開 log
        self.progress_bar.mousePressEvent = self.show_log
        self.mousePressEvent = self.show_log

        # iPadOS 夜間風格圓角卡片
        self.setStyleSheet("""
            QWidget#ProductProgressItem {
                border: 2.2px solid #23293a;
                border-radius: 35px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #252b37, stop:1 #181a20
                );
            }
            QWidget#ProductProgressItem:hover {
                border: 2.2px solid #7ec5ff;
                background: #242735;
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
        self.init_ui()
        self.bv_batch_uploader = None
        self.load_config()
        self.product_status = {}
        self.product_widgets = {}
        self.total_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None
        self.is_paused = False

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(28)
        main_layout.setContentsMargins(78, 54, 78, 54)

        ctl_wrap = QFrame()
        ctl_wrap.setFrameShape(QFrame.StyledPanel)
        ctl_wrap.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #23293a, stop:1 #181a20);
            border-radius: 30px; border:none;
        """)
        ctl_layout = QVBoxLayout()
        ctl_layout.setSpacing(18)
        ctl_layout.setContentsMargins(38, 26, 38, 26)

        row1 = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("來源資料夾")
        self.dir_edit.setStyleSheet("padding:12px 22px; border-radius:16px; background:#20222c; color:#b2bfd3; font-size:1.07em;")
        self.dir_btn = QPushButton("選擇")
        self.dir_btn.setCursor(Qt.PointingHandCursor)
        self.dir_btn.setStyleSheet("padding:10px 40px; border-radius:15px; font-size:1.07em; background:#232b3b; color:#8ab4f8;")
        self.dir_btn.clicked.connect(self.choose_dir)
        row1.addWidget(QLabel("來源資料夾:"))
        row1.addWidget(self.dir_edit, 2)
        row1.addWidget(self.dir_btn)
        ctl_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("帳號")
        self.username_edit.setStyleSheet("padding:10px 16px; border-radius:12px; background:#20222c; color:#b2bfd3;")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密碼")
        self.password_edit.setStyleSheet("padding:10px 16px; border-radius:12px; background:#20222c; color:#b2bfd3;")
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
        self.threads_spin.setStyleSheet("padding:10px 16px; border-radius:12px; background:#20222c; color:#b2bfd3;")
        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("前台主網域（如 https://gd.bvshop.tw）")
        self.domain_edit.setStyleSheet("padding:10px 16px; border-radius:12px; background:#20222c; color:#b2bfd3;")
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
        self.behavior_mode_combo.setStyleSheet("padding:10px 16px; border-radius:12px; background:#20222c; color:#b2bfd3;")
        row4.addWidget(self.headless_checkbox)
        row4.addWidget(QLabel("上架速度模式:"))
        row4.addWidget(self.behavior_mode_combo)
        ctl_layout.addLayout(row4)

        ctl_wrap.setLayout(ctl_layout)
        main_layout.addWidget(ctl_wrap)

        self.summary_label = QLabel("尚未開始")
        self.summary_label.setStyleSheet("font-size: 1.33em; font-weight:600; margin-bottom:14px; color:#a9b5c7;")
        main_layout.addWidget(self.summary_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("尚未開始")
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                height: 54px;
                border: none;
                border-radius: 24px;
                background: #1a1c24;
                text-align: center;
                font-size: 1.31em;
                font-weight: bold;
                color: #bfe1ff;
                margin: 22px 120px 18px 120px;
                min-width: 950px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #53b6ff, stop:0.7 #5edbff, stop:1 #6e80ff);
                border-radius: 24px;
            }
        """)
        main_layout.addWidget(self.overall_progress, alignment=Qt.AlignHCenter)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(50)
        self.grid_layout.setContentsMargins(56, 36, 56, 36)
        self.grid_container.setLayout(self.grid_layout)
        main_layout.addWidget(self.grid_container, stretch=1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始批次上架")
        self.stop_btn = QPushButton("暫停")
        self.resume_btn = QPushButton("繼續")
        self.resume_btn.setEnabled(False)
        self.retry_failed_btn = QPushButton("重跑失敗商品")
        self.exit_btn = QPushButton("結束程式")
        for btn in [self.start_btn, self.stop_btn, self.resume_btn, self.retry_failed_btn, self.exit_btn]:
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #232b3b;
                    border: none;
                    border-radius: 19px;
                    padding: 18px 62px;
                    font-size: 1.13em;
                    color: #8ab4f8;
                    letter-spacing:0.03em;
                }
                QPushButton:hover {
                    background: #2d3754;
                    color: #a7d0ff;
                }
            """)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.retry_failed_btn)
        btn_layout.addWidget(self.exit_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.start_btn.clicked.connect(self.start_batch_upload)
        self.stop_btn.clicked.connect(self.pause_batch_upload)
        self.resume_btn.clicked.connect(self.resume_batch_upload)
        self.retry_failed_btn.clicked.connect(self.retry_failed_uploads)
        self.exit_btn.clicked.connect(self.close)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self.update_time_estimate)
        self.setMinimumSize(1920, 1080)

        app_palette = self.palette()
        app_palette.setColor(QPalette.Window, QColor("#181a20"))
        app_palette.setColor(QPalette.Base, QColor("#20222c"))
        app_palette.setColor(QPalette.Text, QColor("#b8c3d1"))
        app_palette.setColor(QPalette.Button, QColor("#232b3b"))
        self.setPalette(app_palette)

    # ... 其餘業務邏輯與上述 patch 一致（略） ...
