import sys
from PyQt5.QtWidgets import QApplication
from gui import BVShopMainWindow

def main():
    app = QApplication(sys.argv)
    win = BVShopMainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()