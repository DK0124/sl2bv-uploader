from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QPlainTextEdit
)
from PyQt5.QtCore import Qt

class ProductProgressItem(QWidget):
    def __init__(self, name):
        super().__init__()
        self.product_name = name
        self._init_ui()

    def _init_ui(self):
        outer_layout = QVBoxLayout()
        outer_layout.setSpacing(4)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        # 標題 + 狀態
        hbox = QHBoxLayout()
        self.name_label = QLabel(self.product_name)
        self.name_label.setStyleSheet("font-weight:bold; font-size: 1.13em;")
        self.status_label = QLabel("")
        self.status_label.setMinimumWidth(18)
        hbox.addWidget(self.name_label)
        hbox.addStretch()
        hbox.addWidget(self.status_label)
        outer_layout.addLayout(hbox)

        # 進度條
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                height: 20px;
                border: 1px solid #444;
                border-radius: 7px;
                background: #23272b;
                text-align: center;
                font-size: 1.02em;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #42a5f5, stop:1 #66bb6a);
                border-radius: 7px;
            }
        """)
        outer_layout.addWidget(self.progress_bar)

        # 展開/收合log按鈕
        log_hbox = QHBoxLayout()
        self.log_btn = QPushButton("展開log")
        self.log_btn.setCheckable(True)
        self.log_btn.setStyleSheet("QPushButton {font-size:0.98em; padding:2px 10px;}")
        log_hbox.addStretch()
        log_hbox.addWidget(self.log_btn)
        outer_layout.addLayout(log_hbox)

        # log內容
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setVisible(False)
        self.log_box.setMaximumHeight(90)
        self.log_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_box.setStyleSheet("font-size:0.97em; background:#202428; border:1px solid #333; border-radius:5px;")
        outer_layout.addWidget(self.log_box)

        self.setLayout(outer_layout)
        self.log_btn.toggled.connect(self.toggle_log)

        self.log_box.setContextMenuPolicy(Qt.DefaultContextMenu)

        self._log_lines = []

    def update_progress(self, percent, stage_msg=None):
        self.progress_bar.setValue(percent)
        if stage_msg:
            self.append_log(f"[{percent}%] {stage_msg}")

    def set_status(self, success, elapsed, detail_log=""):
        self.progress_bar.setValue(100)
        if success:
            self.status_label.setText("")
            self.status_label.setStyleSheet("")
            self.append_log("✅ 上架成功 - " + (detail_log or "已完成"))
        else:
            self.status_label.setText("❌")
            self.status_label.setStyleSheet("color:#e53935; font-size:1.3em;")
            self.append_log("❌ 上架失敗 - " + (detail_log or "無詳細資訊"))
        if elapsed is not None:
            self.status_label.setToolTip(f"耗時 {elapsed//60}分{elapsed%60}秒")

    def append_log(self, msg):
        self._log_lines.append(msg)
        self.log_box.setPlainText('\n'.join(self._log_lines))

    def toggle_log(self, checked):
        self.log_box.setVisible(checked)
        self.log_btn.setText("收合log" if checked else "展開log")
