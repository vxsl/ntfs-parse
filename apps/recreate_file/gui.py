# Standard library imports
from datetime import timedelta
from time import sleep
from threading import Thread, current_thread
from shutil import disk_usage
from concurrent import futures
from multiprocessing import cpu_count

# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QWidget, QProgressBar, QMessageBox, QVBoxLayout, QGroupBox

# Local imports
from .recreate_file import initialize_job, SourceFile

executor = futures.ThreadPoolExecutor(max_workers=(cpu_count()))

class FinishedDialog(QMessageBox):
    def __init__(self, success, path):
        super().__init__()
        self.setIcon(QMessageBox.Warning)
        if success:
            self.setText('Finished: output written to ' + path)
            #TODO display diff of original vs rebuilt
        else:
            self.setText('Unsuccessful.')
            #TODO not sure what to do here
        self.setStandardButtons(QMessageBox.Ok)

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
        #self.start_at.setText('0')
        #self.start_at.setText('0x404A8A99000')
        #self.start_at.setText('0x404c91a1800')
        self.start_at.setText('0x4191FFA4800')
        #self.start_at.setText('0xaea3d9fe000')
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


        self.inspections_box = QGroupBox("Close inspections")
        self.inspections = QVBoxLayout()
        self.inspections_box.setLayout(self.inspections)
        grid.addWidget(self.inspections_box, 5, 0, 1, 3)
        
        grid.addLayout(successes_hbox, 3, 0)
        grid.addWidget(self.current_addr, 7, 2)
        grid.addWidget(self.progress_bar, 4, 0, 1, 3)

        grid.addWidget(self.start, 9, 0)
        grid.addLayout(start_at_hbox, 10, 0)

        self.setLayout(grid)
        
        current_thread().name = "MAIN GUI THREAD"

    def closeEvent(self, event):
        if not self.job.finished:
            reply = QMessageBox.question(self, 'Window Close', 'Searching is not finished. Are you sure you want to close the window?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                event.accept()
                print('Window closed')
            else:
                event.ignore()

    class inspection_visualizer:
        def __init__(self, inspection, window):
            self.forward = inspection.forward
            self.backward = inspection.backward
            self.forward_label = QLabel('Forward: ')
            self.forward_bar = QProgressBar()
            self.backward_label = QLabel('Backward: ')
            self.backward_bar = QProgressBar()
            self.forward_bar.setTextVisible(False)
            self.backward_bar.setTextVisible(False)
            self.label_prefix = "Close inspection at " + hex(inspection.addr)
            self.label = QLabel(self.label_prefix)
            bars = QHBoxLayout()
            fwdbox = QVBoxLayout()
            bkwdbox = QVBoxLayout()
            fwdbox.addWidget(self.forward_bar)
            fwdbox.addWidget(self.forward_label)
            bkwdbox.addWidget(self.backward_bar)
            bkwdbox.addWidget(self.backward_label)
            bars.addLayout(fwdbox)
            bars.addLayout(bkwdbox)

            window.inspections.addWidget(self.label)
            window.inspections.addLayout(bars)
            window.inspections_box.setLayout(window.inspections)
            
            #Thread(target=self.visualize_inspection_progress).start()
            executor.submit(self.visualize_inspection_progress)
            return

        def visualize_inspection_progress(self):
            while True: 
                self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
                self.forward_bar.setValue(100 * self.forward.sector_count / self.forward.sector_limit)
                self.forward_label.setText('Forward: ' + str(self.forward.sector_count) + '/' + str(self.forward.sector_limit))
                self.backward_bar.setValue(100 * self.backward.sector_count / self.backward.sector_limit)
                self.backward_label.setText('Backward: ' + str(self.backward.sector_count) + '/' + str(self.backward.sector_limit))
                sleep(0.2)                
                if (self.forward.sector_count / self.forward.sector_limit) >= 1:
                    self.forward_bar.setParent(None)
                    self.forward_label.setParent(None)
                if (self.backward.sector_count / self.backward.sector_limit) >= 1:
                    self.backward_bar.setParent(None)
                    self.backward_label.setParent(None)
                if (self.forward.sector_count / self.forward.sector_limit) >= 1 and (self.backward.sector_count / self.backward.sector_limit) >= 1:
                    while executor._work_queue.qsize() > 0:
                        self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
                        sleep(0.5)
                    self.label.setParent(None)
                    break
            return
                

    def invalid_address(self, invalid_input, selected_vol):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(invalid_input + ' is not a valid address.')
        msg.setInformativeText('Please enter a value between 0x0 and ' \
            + str(hex(disk_usage(selected_vol + ':\\').total).upper() + '.'))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()


    def go(self, selected_vol, source_file):

        start_at_input = self.start_at.text()
        try:
            if 0 <= int(start_at_input, 16) <= disk_usage(selected_vol + ':\\').total:
                start_at = int(start_at_input, 16)
            else: 
                self.invalid_address(start_at_input, selected_vol)
                return
        except ValueError:
            self.invalid_address(start_at_input, selected_vol)
            return

        self.job = initialize_job(self.do_logging, self.express_mode.isChecked(), selected_vol, source_file, executor)
        self.job.success_signal.connect(self.visualize_file_progress)
        self.job.new_inspection_signal.connect(lambda inspection: self.inspection_visualizer(inspection, self))
        self.job.finished_signal.connect(self.finished)

        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)
        self.express_mode.setDisabled(True)
        self.do_logging.setDisabled(True)

        #Thread(name='visualize read progress',target=self.visualize_read_progress).start()
        executor.submit(self.visualize_read_progress)

        #recreate_main = Thread(name='recreate main',target=self.job.primary_reader.read,args=[start_at])
        executor.submit(self.job.primary_reader.read, start_at)
        self.job.perf.start()
        #recreate_main.start()

    def finished(self, success):
        FinishedDialog(success, self.job.rebuilt_file_path).exec()
        #self.close()

    def visualize_file_progress(self, i):
        self.job.done_sectors += 1
        self.successes.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
        + "%\n\n Testing equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))

    def visualize_read_progress(self):
        current_thread().name = "Visualize read progress"
        while True:
            if not self.job.primary_reader.inspections:
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
            else:
                self.time_remaining.setText(self.get_remaining_estimate(progress))                    
            sleep(1)

    def get_remaining_estimate(self, progress):
        if not self.job.primary_reader.inspections:
            seconds = self.job.perf.avg * ((self.job.diskSize.total - progress) / (512 * self.job.perf.sample_size))
            return "At most " + str(timedelta(seconds=seconds)).split(".")[0] + " remaining to traverse disk"
        else:
            return str(len(self.job.primary_reader.inspections)) + " close inspections in progress."