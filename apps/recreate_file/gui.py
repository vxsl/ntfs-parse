# Standard library imports
from threading import current_thread
from shutil import disk_usage
import sys

# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QWidget, QProgressBar, QMessageBox, QVBoxLayout, QGroupBox

# Local imports
from .recreate_file import initialize_job, SourceFile

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

class ChooseSourceFileDialog(QFileDialog):
    def __init__(self):
        super(ChooseSourceFileDialog, self).__init__()
        self.setWindowTitle("Choose source file")

class MainWindow(QWidget):
    def __init__(self, selected_vol):
        super().__init__()
        self.setWindowTitle("ntfs-toolbox")

        dlg = ChooseSourceFileDialog()
        dlg.exec()
        path = dlg.selectedFiles()[0]

        self.file = SourceFile(path)
        self.selected_vol = selected_vol

        file_info = QGridLayout()
        file_info.addWidget(QLabel('Source file name:'), 0, 0)
        file_info.addWidget(QLabel(self.file.name), 0, 1)
        file_info.addWidget(QLabel('Source file location:'), 1, 0)
        file_info.addWidget(QLabel(self.file.dir), 1, 1)
        file_info.addWidget(QLabel('Size:'), 2, 0)
        file_info.addWidget(QLabel(str(len(self.file.remaining_sectors)) + " sectors"), 2, 1)

        self.start_at = QLineEdit()
        self.start_at.setText('0')
        #self.start_at.setText('0x9b4d70800')
        #self.start_at.setText('0x404A8A99000')
        #self.start_at.setText('0x404c91a1800')
        self.start_at.setText('0x4191FFA4800')
        #self.start_at.setText('0xaea3d9fe000')
        start_at_hbox = QHBoxLayout()
        start_at_label = QLabel("Start at address (search forward): ")
        start_at_hbox.addWidget(start_at_label)
        start_at_hbox.addWidget(self.start_at)

        self.successes = QLabel()
        self.successes.setText("0/" + (str(len(self.file.remaining_sectors))))
        successes_hbox = QHBoxLayout()
        successes_hbox.addWidget(self.successes)


        self.skim_progress_bar = QProgressBar()
        self.skim_progress_bar.setTextVisible(False)
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
        self.start.clicked.connect(self.request_test_run)

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
        grid.addWidget(self.skim_progress_bar, 4, 0, 1, 3)

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
                sys.exit()
            else:
                event.ignore()

    class inspection_gui:
        def __init__(self, inspection, window):
            self.forward = inspection.forward
            self.backward = inspection.backward
            self.label_prefix = "Close inspection at " + hex(inspection.addr)
            self.label = QLabel(self.label_prefix)
            self.time_estimate = QLabel("Calculating time remaining...")
            
            self.inspections = {
                "forward": {
                    "process":self.forward,
                    "bar":QProgressBar(),
                    "label":QLabel(self.label_prefix)
                },
                "backward": {
                    "process":self.backward,
                    "bar":QProgressBar(),
                    "label":QLabel(self.label_prefix)
                }
            }
            
            bars = QHBoxLayout()

            for key in self.inspections:
                box = QVBoxLayout()
                self.inspections[key]['bar'].setTextVisible(False)
                box.addWidget(self.inspections[key]['bar'])
                box.addWidget(self.inspections[key]['label'])
                bars.addLayout(box)

            window.inspections.addWidget(self.label)
            window.inspections.addLayout(bars)
            window.inspections_box.setLayout(window.inspections)
            
            self.forward.inspection_progress_signal.connect(lambda: self.inspection_gui_update('forward'))
            self.backward.inspection_progress_signal.connect(lambda: self.inspection_gui_update('backward'))

            #executor.submit(self.inspection_gui_update)
            return

        def inspection_gui_update(self, which):
            #self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
            
            #for inspection in self.inspections:
            inspection = self.inspections[which]
            if not inspection['process'].finished:
                inspection['bar'].setValue(100 * inspection['process'].sector_count / inspection['process'].sector_limit)            
                if inspection['process'].perf.avg > 0:    
                    inspection['label'].setText(which + ': ' + str(inspection['process'].sector_count) + '/' + str(inspection['process'].sector_limit) \
                                        + '\n' + inspection['process'].perf.get_remaining_estimate() \
                                        + '\naverage read = ' + '{:.2f}'.format(inspection['process'].perf.avg) + ' s' \
                                        + '\n' + '{:.4f}'.format(100 * inspection['process'].success_count / inspection['process'].sector_count) + "% success")
                else:
                    inspection['label'].setText(which + ': ' + str(inspection['process'].sector_count) + '/' + str(inspection['process'].sector_limit) \
                                        + '\n...\n...\n...')
            else:
                inspection['bar'].setParent(None)
                inspection['label'].setParent(None)
                #self.inspections.remove(inspection)
                del inspection
            
            """ if not self.inspections:
                while executor._work_queue.qsize() > 0:
                    self.label.setText(self.label_prefix + ": " + str(executor._work_queue.qsize()) + " sectors in the queue")
                    sleep(0.5)
                self.label.setParent(None)
                break   """              
                

    def invalid_address(self, invalid_input, selected_vol):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(invalid_input + ' is not a valid address.')
        msg.setInformativeText('Please enter a value between 0x0 and ' \
            + str(hex(disk_usage(selected_vol + ':\\').total).upper() + '.'))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()       

    def validate_hex(self, inp):
        try:
            if 0 <= int(inp, 16) <= disk_usage(self.selected_vol + ':\\').total:
                self.start.setText('...')
                self.start.setDisabled(True)
                self.start_at.setDisabled(True)
                self.express_mode.setDisabled(True)
                self.do_logging.setDisabled(True)                
                return int(inp, 16)
            else:  
                return None
        except ValueError:
            return None
            
    def request_test_run(self):

        user_input = self.start_at.text()
        validated_start_address = self.validate_hex(user_input)
        if validated_start_address is None:
            self.invalid_address(user_input, self.selected_vol)
            return
        
        self.skim_progress_bar.setTextVisible(True)
        self.skim_progress_bar.setFormat("Loading...")
        self.skim_progress_bar.setAlignment(QtCore.Qt.AlignCenter)
        
        self.job_thread = QtCore.QThread()
        self.job_thread.start()        
        self.job = initialize_job(True, self.selected_vol, self.file, self.express_mode.isChecked())
        self.job.moveToThread(self.job_thread)

        self.job.do_test_run.emit()
        self.job.loading_progress_signal.connect(self.skim_progress_bar.setValue)
        self.job.loading_complete_signal.connect(lambda init_avg: self.go(init_avg, validated_start_address))

    def go(self, init_avg, start_at):
        
        self.skim_progress_bar.setTextVisible(False)
        self.skim_progress_bar.setFormat(None)
        self.job.success_signal.connect(self.visualize_file_progress)
        self.job.new_inspection_signal.connect(lambda inspection: self.inspection_gui(inspection, self))
        self.job.finished_signal.connect(self.finished)
        self.job.skim_progress_signal.connect(self.skim_gui_update)
        self.job.start.emit([start_at, init_avg])               

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

    def skim_gui_update(self):
        #print('gui update')
        progress =  self.job.perf.sectors_read
        percent = 100 * progress / self.job.perf.total_sectors_to_read
        self.progress_percentage.setText("{:.8f}".format(percent) + "%")
        self.skim_progress_bar.setValue(percent)
        self.sector_avg.setText("Average time to traverse " \
        + str(self.job.perf.sample_size * self.job.perf.jump_size) \
        + " sectors (" + str(self.job.perf.sample_size * self.job.perf.jump_size * 512 / 1000000) \
        + " MB): {:.2f}".format(self.job.perf.avg) + " seconds")
        self.time_remaining.setText(self.job.perf.get_remaining_estimate())