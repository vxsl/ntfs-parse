import string
import os
from PyQt5.QtWidgets import QFileDialog, QDialog, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox, QVBoxLayout, QApplication, QCheckBox
import gui

class ChooseSourceFileDialog(QFileDialog):
    def __init__(self):
        super(ChooseSourceFileDialog, self).__init__()
        self.setWindowTitle("Choose source file")

class StartDialog(QDialog):
    def __init__(self):

        super(StartDialog, self).__init__()

        vbox = QVBoxLayout()
        label = QLabel("Select the corrupt disk or logical volume of interest.")
        self.vol_select_dropdown = QComboBox(self)
        vbox.addWidget(label)
        vbox.addWidget(self.vol_select_dropdown)

        self.include_raw = QCheckBox("Include raw disks ")
        self.include_raw.setStyleSheet("font-style:italic")
        self.include_raw.stateChanged.connect(self.render_vols)
        self.include_raw.setChecked(True)

        self.vol_select_dropdown.setCurrentText("D:")    # TODO remove
        qbtn = QDialogButtonBox.Ok
        self.button_box = QDialogButtonBox(qbtn)
        self.button_box.accepted.connect(self.accept)
        vbox.addWidget(self.include_raw)
        vbox.setSpacing(10)

        layout = QVBoxLayout()
        layout.addLayout(vbox)        
        layout.addWidget(self.button_box)
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(50)
        self.setLayout(layout)

    def render_vols(self):
        if self.include_raw.isChecked():
            vols = ['%s:' % v for v in string.ascii_uppercase if os.path.exists('%s:' % v)]
            vols += ['Raw disk %s' % d for d in range(50) if os.path.exists('\\\\.\\PhysicalDrive%s' % d)]
        else:
            vols = ['%s:' % v for v in string.ascii_uppercase if os.path.exists('%s:' % v)]

        self.vol_select_dropdown.clear()
        self.vol_select_dropdown.addItems(vols)

app = QApplication([])

disk_select = StartDialog()
disk_select.setWindowTitle('recoverability')
disk_select.exec()

selected_vol = disk_select.vol_select_dropdown.currentText()[0]

file_select = ChooseSourceFileDialog()
file_select.exec()
path = file_select.selectedFiles()[0]

window = gui.MainWindow(selected_vol, path)
window.setWindowTitle('recoverability')
window.setGeometry(500, 500, 500, 600)
window.show()

app.exec_()