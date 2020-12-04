# Standard library imports
from datetime import timedelta
from time import sleep
from threading import Thread, current_thread
from shutil import disk_usage
from concurrent import futures
from multiprocessing import cpu_count
from sys import exit

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

        file = SourceFile(path)

        file_info = QGridLayout()
        file_info.addWidget(QLabel('Source file name:'), 0, 0)
        file_info.addWidget(QLabel(file.name), 0, 1)
        file_info.addWidget(QLabel('Source file location:'), 1, 0)
        file_info.addWidget(QLabel(file.dir), 1, 1)
        file_info.addWidget(QLabel('Size:'), 2, 0)
        file_info.addWidget(QLabel(str(len(file.remaining_sectors)) + " sectors"), 2, 1)

        self.start_at = QLineEdit()
        self.start_at.setText('0')
        self.start_at.setText('0x9b4d70800')
        #self.start_at.setText('0x404A8A99000')
        #self.start_at.setText('0x404c91a1800')
        #self.start_at.setText('0x4191FFA4800')
        #self.start_at.setText('0xaea3d9fe000')
        start_at_hbox = QHBoxLayout()
        start_at_label = QLabel("Start at address (search forward): ")
        start_at_hbox.addWidget(start_at_label)
        start_at_hbox.addWidget(self.start_at)

        self.successes = QLabel()
        self.successes.setText("0/" + (str(len(file.remaining_sectors))))
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
        self.do_logging.setChecked(True)

        self.current_addr = QPushButton('Display current address')
        self.current_addr.clicked.connect(lambda: self.current_addr.setText(hex(self.job.primary_reader.fd.tell())))

        self.start = QPushButton('Start')
        self.start.clicked.connect(lambda: self.go(selected_vol, file))

        grid = QGridLayout()
        grid.addLayout(file_info, 0, 0)

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
                exit()
            else:
                event.ignore()

    class inspection_visualizer:
        def __init__(self, inspection, window):
            self.forward = inspection.forward
            self.backward = inspection.backward
            self.label_prefix = "Close inspection at " + hex(inspection.addr)
            self.label = QLabel(self.label_prefix)
            self.time_estimate = QLabel("Calculating time remaining...")
            
            self.inspections = [
                {
                    "name":"Forward",
                    "process":self.forward,
                    "bar":QProgressBar(),
                    "label":QLabel(self.label_prefix)
                },
                {
                    "name":"Backward",
                    "process":self.backward,
                    "bar":QProgressBar(),
                    "label":QLabel(self.label_prefix)
                }
            ]   
            
            bars = QHBoxLayout()

            for inspection in self.inspections:
                box = QVBoxLayout()
                inspection['bar'].setTextVisible(False)
                box.addWidget(inspection['bar'])
                box.addWidget(inspection['label'])
                bars.addLayout(box)

            window.inspections.addWidget(self.label)
            window.inspections.addLayout(bars)
            window.inspections_box.setLayout(window.inspections)
            
            #Thread(target=self.visualize_inspection_progress).start()
            executor.submit(self.visualize_inspection_progress)
            return

        def visualize_inspection_progress(self):
            while True: 
                self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
                
                for inspection in self.inspections:
                    if not inspection['process'].finished:
                        inspection['bar'].setValue(100 * inspection['process'].sector_count / inspection['process'].sector_limit)            
                        if inspection['process'].perf.avg > 0:    
                            inspection['label'].setText(inspection['name'] + ': ' + str(inspection['process'].sector_count) + '/' + str(inspection['process'].sector_limit) \
                                                + '\n' + inspection['process'].perf.get_remaining_estimate() \
                                                + '\naverage read = ' + '{:.2f}'.format(inspection['process'].perf.avg) + ' s' \
                                                + '\n' + '{:.4f}'.format(100 * inspection['process'].success_count / inspection['process'].sector_count) + "% success")
                        else:
                            inspection['label'].setText(inspection['name'] + ': ' + str(inspection['process'].sector_count) + '/' + str(inspection['process'].sector_limit) \
                                                + '\n...\n...\n...')
                    else:
                        inspection['bar'].setParent(None)
                        inspection['label'].setParent(None)
                        self.inspections.remove(inspection)
                
                if not self.inspections:
                    while executor._work_queue.qsize() > 0:
                        self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
                        sleep(0.5)
                    self.label.setParent(None)
                    break                
                sleep(0.2)                
            return
                

    def invalid_address(self, invalid_input, selected_vol):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(invalid_input + ' is not a valid address.')
        msg.setInformativeText('Please enter a value between 0x0 and ' \
            + str(hex(disk_usage(selected_vol + ':\\').total).upper() + '.'))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()


    def go(self, selected_vol, file):

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

        self.job = initialize_job(self.do_logging, self.express_mode.isChecked(), selected_vol, file, executor)
        self.job.success_signal.connect(self.visualize_file_progress)
        self.job.new_inspection_signal.connect(lambda inspection: self.inspection_visualizer(inspection, self))
        self.job.finished_signal.connect(self.finished)

        self.job.ready_signal.connect(lambda: executor.submit(self.visualize_skim_progress))

        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)
        self.express_mode.setDisabled(True)
        self.do_logging.setDisabled(True)

        #Thread(name='visualize read progress',target=self.visualize_read_progress).start()

        #recreate_main = Thread(name='recreate main',target=self.job.primary_reader.read,args=[start_at])
        executor.submit(self.job.begin, start_at)        
        #self.job.perf.start()
        #recreate_main.start()

    def finished(self, success):
        FinishedDialog(success, self.job.rebuilt_file_path).exec()
        self.close()

    def visualize_file_progress(self, i):
        self.job.done_sectors += 1
        self.successes.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
        + "%\n\n Testing equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))

    def visualize_skim_progress(self):
        current_thread().name = "Visualize read progress"
        while True:
            #if not self.job.primary_reader.inspections:
            #progress = self.job.primary_reader.fd.tell()
            progress =  self.job.perf.sectors_read
            #percent = 100 * progress / self.job.diskSize.total
            percent = 100 * progress / self.job.perf.total_sectors_to_read
            self.progress_percentage.setText("{:.3f}".format(percent) + "%")
            self.progress_bar.setValue(percent)
            self.sector_avg.setText("Average time to traverse " \
            + str(self.job.perf.sample_size * self.job.perf.skip_size) \
            + " sectors (" + str(self.job.perf.sample_size * self.job.perf.skip_size * 512 / 1000000) \
            + " MB): {:.2f}".format(self.job.perf.avg) + " seconds")
            self.time_remaining.setText(self.job.perf.get_remaining_estimate())
            sleep(0.2)