import string
import os
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox, QVBoxLayout, QApplication
from apps.raw_gz import raw_gz
from recreate_file import gui

class StartDialog(QDialog):
    def __init__(self):

        super(StartDialog, self).__init__()
        self.setWindowTitle("raw-gz")

        vols = ['%s:' % v for v in string.ascii_uppercase if os.path.exists('%s:' % v)]
        progs = ["locate and unpack .gzip archives", "recreate file"]

        hbox1 = QHBoxLayout()
        vol_select_label = QLabel("Logical volume: ")
        self.vol_select_dropdown = QComboBox(self)

        self.vol_select_dropdown.addItems(vols)
        self.vol_select_dropdown.setCurrentText("D:")    # TODO remove
        hbox1.addWidget(vol_select_label)
        hbox1.addWidget(self.vol_select_dropdown)

        hbox2 = QHBoxLayout()
        prog_select_label = QLabel("Program: ")
        self.prog_select_dropdown = QComboBox(self)
        self.prog_select_dropdown.addItems(progs)
        self.prog_select_dropdown.setCurrentText("recreate file")  # TODO remove

        hbox2.addWidget(prog_select_label)
        hbox2.addWidget(self.prog_select_dropdown)

        qbtn = QDialogButtonBox.Ok
        self.button_box = QDialogButtonBox(qbtn)
        self.button_box.accepted.connect(self.accept)


        vert = QVBoxLayout()
        vert.addLayout(hbox1)
        vert.addLayout(hbox2)
        vert.addWidget(self.button_box)
        self.setLayout(vert)


app = QApplication([])

dlg = StartDialog()
dlg.setWindowTitle('ntfs-parse')

dlg.show()
app.exec_()

selected_vol = dlg.vol_select_dropdown.currentText()[0]
selected_prog = dlg.prog_select_dropdown.currentText()

if selected_prog == "locate and unpack .gzip archives":
    new_app = QApplication([])
    window = raw_gz.MainWindow(selected_vol)
    window.setWindowTitle('raw_gz')
    window.setGeometry(500, 500, 500, 300)
    window.show()
    new_app.exec_()

elif selected_prog == "recreate file":
    new_app = QApplication([])
    window = gui.MainWindow(selected_vol)
    window.setWindowTitle('recreate_file')
    window.setGeometry(500, 500, 500, 600)
    window.show()
    new_app.exec_()
