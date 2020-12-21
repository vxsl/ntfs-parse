import string
import os
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QDialog, \
    QHBoxLayout, QLabel, QComboBox, QDialogButtonBox, QVBoxLayout, \
    QApplication, QCheckBox
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
file_select = ChooseSourceFileDialog()

while True:
    disk_select.exec()
    selected_vol = disk_select.vol_select_dropdown.currentText()[0]
    file_select.exec()
    path = file_select.selectedFiles()[0]
    if os.stat(path).st_size > 100000000:
        error = QMessageBox()
        error.setWindowTitle('recoverability')
        error.setIcon(QMessageBox.Warning)
        error.setText('Please select a file under 100 MB. Searching for large files is not yet implemented.')
        error.setStandardButtons(QMessageBox.Ok)
        error.exec()
    elif path.split(":")[0] == selected_vol:
        error = QMessageBox()
        error.setWindowTitle('recoverability')
        error.setIcon(QMessageBox.Warning)
        error.setText('Your source file cannot be loaded from the same volume you are searching, because the rebuilt file will be created in the same directory.\n\nPlease choose a different source file or volume to search.')
        error.setStandardButtons(QMessageBox.Ok)
        error.exec()
    else:
        break

window = gui.MainWindow(selected_vol, path)
window.setWindowTitle('recoverability')
window.setGeometry(500, 500, 500, 600)
window.show()

app.exec_()