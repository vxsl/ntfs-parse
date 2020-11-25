# Standard library imports
from datetime import timedelta
from time import sleep
from threading import Thread

# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QWidget, QProgressBar, QMessageBox

# Local imports
from recreate_file import initialize_job, SourceFile


class ChooseReferenceFileDialog(QFileDialog):
    def __init__(self):
        super(ChooseReferenceFileDialog, self).__init__()
        self.setWindowTitle("Choose source file")

class MainWindow(QWidget):
    def __init__(self, selected_vol):
        super().__init__()
        self.setWindowTitle("ntfs-toolbox")

        dlg = ChooseReferenceFileDialog()
        dlg.exec()
        path = dlg.selectedFiles()[0]

        source_file = SourceFile(path)

        source_file_info = QGridLayout()
        source_file_info.addWidget(QLabel('Source file name:'), 0, 0)
        source_file_info.addWidget(QLabel(source_file.name), 0, 1)
        source_file_info.addWidget(QLabel('Source file location:'), 1, 0)
        source_file_info.addWidget(QLabel(source_file.dir), 1, 1)
        source_file_info.addWidget(QLabel('Size:'), 2, 0)
        source_file_info.addWidget(QLabel(str(len(source_file.sectors)) + " sectors"), 2, 1)

        self.start_at = QLineEdit()
        #self.start_at.setText('0x404A8A99000')
        self.start_at.setText('0x404c91a1800')
        start_at_hbox = QHBoxLayout()
        start_at_label = QLabel("Start at address (search forward): ")
        start_at_hbox.addWidget(start_at_label)
        start_at_hbox.addWidget(self.start_at)

        self.successes = QLabel()
        self.successes.setText("0/" + (str(len(source_file.sectors))))
        successes_hbox = QHBoxLayout()
        successes_hbox.addWidget(self.successes)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_percentage = QLabel()
        self.sector_avg = QLabel()

        self.time_remaining = QLabel()

        self.express_mode = QCheckBox("Express mode (only disable for small volumes): ")
        self.express_mode.setChecked(True)

        self.do_logging = QCheckBox("Log (./ntfs-toolbox/...): ")
        self.do_logging.setChecked(False)

        self.current_addr = QPushButton('Display current address')
        self.current_addr.clicked.connect(lambda: self.current_addr.setText(hex(self.job.primary_reader.fd.tell())))

        self.start = QPushButton('Start')
        self.start.clicked.connect(lambda: self.go(selected_vol, source_file))

        grid = QGridLayout()
        grid.addLayout(source_file_info, 0, 0)

        grid.addWidget(self.express_mode, 7, 0)
        grid.addWidget(self.do_logging, 8, 0)

        self.progress_percentage.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.progress_percentage, 6, 2)

        self.sector_avg.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.sector_avg, 9, 2)

        self.time_remaining.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.time_remaining, 8, 2)

        grid.addLayout(successes_hbox, 3, 0)
        grid.addWidget(self.current_addr, 7, 2)
        grid.addWidget(self.progress_bar, 4, 0, 4, 3)
        grid.addWidget(self.start, 9, 0)
        grid.addLayout(start_at_hbox, 10, 0)

        self.setLayout(grid)

    def go(self, selected_vol, reference_file):

        start_at_input = self.start_at.text()
        try:
            start_at = int(start_at_input, 16)
        except ValueError:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText(start_at_input + ' is not a valid hexadecimal address.')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            return

        self.job = initialize_job(self.do_logging, self.express_mode.isChecked(), selected_vol, reference_file)
        self.job.success_update.connect(self.visualize_file_progress)

        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)
        self.express_mode.setDisabled(True)
        self.do_logging.setDisabled(True)

        recreate_main = Thread(name='recreate main',target=self.job.primary_reader.read,args=[start_at])
        self.job.perf.start()
        recreate_main.start()

        Thread(name='visualize read progress',target=self.visualize_read_progress).start()
        # ...
        #recreate_main.join()
        #print("Program terminated")

    def visualize_file_progress(self, i):
        self.job.done_sectors += 1
        self.successes.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.4f}".format(self.job.done_sectors / self.job.total_sectors) \
        + "%\n\n Testing equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))

    def visualize_read_progress(self):
        while True:
            progress = self.job.primary_reader.fd.tell()
            percent = 100 * progress / self.job.diskSize.total
            self.progress_percentage.setText("{:.2f}".format(percent) + "%")
            self.progress_bar.setValue(percent)
            if self.job.perf.avg > 0:
                self.sector_avg.setText("Average time to traverse " \
                + str(self.job.perf.sample_size) \
                + " sectors (" + str(self.job.perf.sample_size * 512 / 1000000) \
                + " MB): {:.2f}".format(self.job.perf.avg) + " seconds")
                self.time_remaining.setText(self.get_remaining_estimate(progress))
            else:
                self.sector_avg.setText("Average time to traverse " \
                + str(self.job.perf.sample_size) + " sectors (" \
                + str(self.job.perf.sample_size * 512 / 1000000) \
                + " MB): calculating...")
                self.time_remaining.setText("Calculating time remaining...")
            sleep(1)

    def get_remaining_estimate(self, progress):
        seconds = self.job.perf.avg * ((self.job.diskSize.total - progress) / (512 * self.job.perf.sample_size))
        return str("At most ~" + timedelta(seconds=seconds)).split(".")[0] + " remaining"