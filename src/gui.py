# Standard library imports
from threading import current_thread, Lock
from shutil import disk_usage
import sys
# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, \
                            QLabel, QLineEdit, QPushButton, \
                            QWidget, QProgressBar, QMessageBox, \
                            QVBoxLayout, QGroupBox

# Local imports
from recreate_file import Job, SECTOR_SIZE

inspection_gui_manipulation_mutex = Lock()

class SourceFile():
    def __init__(self, path):
        self.remaining_sectors = self.to_sectors(path)
        self.address_table = [[] for _ in range(len(self.remaining_sectors))]
        #self.remaining_sectors = copy.deepcopy(self.sectors)
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def to_sectors(self, path):
        fobj = open(path, "rb")
        fobj.seek(0)
        result = []
        while True:
            cur = fobj.read(SECTOR_SIZE)
            if cur == b'':
                break
            elif len(cur) == SECTOR_SIZE:
                result.append(cur)
            else:
                result.append(\
                (bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1]))))   #trailing sector zfill
        return result

class ChildInspection(QtCore.QObject):
    def __init__(self, id_tuple, sector_limit, prefix, estimate_fn):
        super().__init__()
        self.address = id_tuple[2]
        self.finished = False
        self.sibling = None
        self.id_str = id_tuple[0] + id_tuple[2]
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.label = QLabel(prefix)
        self.label.setStyleSheet("font-weight: bold")
        self.sector_limit = sector_limit
        self.avg = 0
        self.estimate_fn = estimate_fn

    @QtCore.pyqtSlot(tuple)
    def update(self, info):
        self.progress_bar.setValue(100 * info[0] / self.sector_limit)
        if self.avg > 0:
            self.label.setText(str(info[0]) + '/' + str(self.sector_limit) \
                                + '\n' + '{:.4f}'.format(100 * info[1] / info[0]) \
                                + "% success")
        else:
            self.label.setText(str(info[0]) + '/' + str(self.sector_limit) \
                                + '\nCalculating...')

class MainWindow(QWidget):
    def __init__(self, selected_vol, path):
        super().__init__()
        self.setWindowTitle("recoverability")            
        current_thread().name = "GUI thread"  

        self.job_thread = QtCore.QThread()
        self.job = None

        self.file = SourceFile(path)
        self.selected_vol = selected_vol

        file_info_box = QGroupBox("Source file")
        file_info = QGridLayout()
        file_info.addWidget(QLabel('Name:'), 0, 0)
        file_info.addWidget(QLabel(self.file.name), 0, 1)
        file_info.addWidget(QLabel('Location:'), 1, 0)
        file_info.addWidget(QLabel(self.file.dir), 1, 1)
        file_info.addWidget(QLabel('Size:'), 2, 0)
        file_info.addWidget(QLabel(str(len(self.file.remaining_sectors)) + " sectors"), 2, 1)
        file_info_box.setLayout(file_info)
        
        rebuilt_file_group_box = QGroupBox("Reconstructed file")
        rebuilt_file_hbox = QHBoxLayout()
        self.rebuilt_file_info = QLabel()
        self.rebuilt_file_info.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.rebuilt_file_info.setText(("Last match: (none)\n\n") \
        + ("0/" + (str(len(self.file.remaining_sectors))) \
        + " = " + "0.00%" \
        + "\n\nTesting equality for " + (str(len(self.file.remaining_sectors))) \
        + " remaining sectors..."))
        rebuilt_file_hbox.addWidget(self.rebuilt_file_info)
        rebuilt_file_group_box.setLayout(rebuilt_file_hbox)

        files_hbox = QHBoxLayout()
        files_hbox.addWidget(file_info_box)
        files_hbox.addWidget(rebuilt_file_group_box)

        skim_group_box = QGroupBox("Skim")
        skim_grid = QGridLayout()
        self.skim_progress_bar = QProgressBar()
        self.skim_progress_bar.setTextVisible(False)
        self.skim_percentage = QLabel()
        self.skim_percentage.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.skim_address_button = QPushButton('Display current address in skim')
        self.skim_address_button.clicked.connect(self.display_current_skim_address)
        skim_grid.addWidget(self.skim_progress_bar, 0, 0, 1, 3)
        skim_grid.addWidget(self.skim_percentage, 1, 2)
        skim_grid.addWidget(self.skim_address_button, 1, 0)
        skim_group_box.setLayout(skim_grid)

        self.sector_average = QLabel()

        self.time = QtCore.QTime(0, 0, 0)
        self.time_label = QLabel()
        self.clock = QtCore.QTimer(self)
        self.clock.timeout.connect(self.draw_clock)

        self.inspection_labels = {}
        self.current_inspections = {}
        self.current_inspection_averages = {}
        self.current_slowest_inspection = None
        self.inspection_sample_size = None

        self.inspections_box = QGroupBox("Close inspections")
        self.inspections_vbox = QVBoxLayout()
        self.inspections_box.setLayout(self.inspections_vbox)
        self.inspections_box.hide()

        start_hbox = QHBoxLayout()

        self.start_button = QPushButton('Start')
        self.start_button.clicked.connect(self.start)

        self.init_address_input = QLineEdit()
        self.init_address_input.setPlaceholderText('Begin at address (default 0x0000000000)')
        init_address_hbox = QHBoxLayout()
        init_address_hbox.addWidget(self.init_address_input)

        start_hbox.addLayout(init_address_hbox)
        start_hbox.addWidget(self.start_button)

        grid = QGridLayout()
        grid.setSpacing(50)
        grid.setContentsMargins(50, 50, 50, 50)
        
        grid.addLayout(files_hbox, 0, 0) 
        grid.addWidget(skim_group_box, 4, 0)
        grid.addWidget(self.inspections_box, 5, 0)
        grid.addWidget(self.sector_average, 7, 0)
        grid.addWidget(self.time_label, 8, 0)

        grid.addLayout(start_hbox, 9, 0)

        self.setLayout(grid)

    @QtCore.pyqtSlot()
    def display_current_skim_address(self):
        if hasattr(self, 'job'):
        if not self.current_inspections:
            self.skim_address_button.setText(hex(self.job.skim_reader.fobj.tell()))
        else:
            self.skim_address_button.setText(hex(self.job.skim_reader.fobj.tell()) + ' (paused)')
        else:
            self.skim_address_button.setText("Skim has not been started.")
        QtCore.QTimer.singleShot(2000, lambda: self.skim_address_button.setText('Display current address in skim'))

    @QtCore.pyqtSlot()
    def draw_clock(self):
        if self.current_inspections:
            if self.current_slowest_inspection:
                self.time = self.time.addSecs(-1)                
                the_time = self.time.toString("h:mm:ss")
                self.time_label.setText("Average time to parse " \
                    + str(len(self.current_inspections) * self.inspection_sample_size) \
                    + "+ sectors: " + "{:.2f}".format(self.current_slowest_inspection.avg) \
                    + " s\n" + the_time + " remaining to finish current close inspections.\n")
            else:
                self.time_label.setText(self.time.toString("h:mm:ss") + \
                    " remaining in skim (paused)... calculating time remaining in close inspection(s).")
        else:
            self.time = self.time.addSecs(-1)                
            the_time = self.time.toString("h:mm:ss")
            self.time_label.setText(the_time + " remaining in skim")
            
    def closeEvent(self, event):
        if hasattr(self, 'job'):
        if not self.job.finished:
            reply = QMessageBox.question(self, 'Window Close', 'Searching is not finished. Are you sure you want to close the window?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                event.accept()
                sys.exit()
            else:
                event.ignore()
        else:
            event.accept()
            sys.exit()

    @QtCore.pyqtSlot(tuple)
    def new_skim_average(self, data):
        avg = data[0]
        estimate = data[1]
        self.sector_average.setText("Average time to skim " \
            + str(self.job.skim_reader.perf.sample_size * self.job.skim_reader.perf.jump_size) + " sectors (" \
            + str(self.job.skim_reader.perf.sample_size * self.job.skim_reader.perf.jump_size * 512 / 1000000) \
            + " MB): {:.2f}".format(avg) + " seconds")
        self.time.setHMS(0,0,0)
        self.time = self.time.addSecs(estimate)

    @QtCore.pyqtSlot(tuple)
    def new_inspection_average(self, data):
        avg = data[0]
        id_str = data[1]

        self.current_inspections[id_str].avg = avg
        self.current_inspection_averages[id_str] = avg
        if len(self.current_inspection_averages) == len(self.current_inspections):
            slowest = max(self.current_inspections, key=lambda x: self.current_inspections[x].avg)
            secs = self.current_inspections[slowest].estimate_fn()
            if secs == '...':
                return
            self.current_slowest_inspection = self.current_inspections[slowest]
            self.time.setHMS(0,0,0)
            self.time = self.time.addSecs(secs)
            del self.current_inspection_averages
            self.current_inspection_averages = {}

    @QtCore.pyqtSlot(tuple)
    def initialize_inspection_gui(self, data):
        address = data[0]
        forward = data[1]
        backward = data[2]

        self.skim_progress_bar.setTextVisible(True)
        self.skim_progress_bar.setFormat("Paused")

        inspection_gui_manipulation_mutex.acquire()
        label_prefix = hex(address)
        self.inspection_labels[label_prefix] = QLabel(label_prefix)
        self.inspection_labels[label_prefix].setStyleSheet("font-weight: bold")

        forward.perf.new_average_signal.connect(self.new_inspection_average)
        backward.perf.new_average_signal.connect(self.new_inspection_average)
        forward_gui = ChildInspection(forward.id_tuple, forward.sector_limit, label_prefix, forward.perf.get_remaining_estimate)
        backward_gui = ChildInspection(backward.id_tuple, backward.sector_limit, label_prefix, backward.perf.get_remaining_estimate)

        forward_gui.sibling = backward_gui
        backward_gui.sibling = forward_gui

        bars = QHBoxLayout()

        # add forward to layout
        box = QVBoxLayout()
        box.addWidget(forward_gui.progress_bar)
        box.addWidget(forward_gui.label)
        bars.addLayout(box)

        # add backward to layout
        box = QVBoxLayout()
        box.addWidget(backward_gui.progress_bar)
        box.addWidget(backward_gui.label)
        bars.addLayout(box)

        self.inspections_vbox.addWidget(self.inspection_labels[label_prefix])
        self.inspections_vbox.addLayout(bars)

        self.inspections_box.show()

        self.current_inspections[forward_gui.id_str] = forward_gui
        self.current_inspections[backward_gui.id_str] = backward_gui

        inspection_gui_manipulation_mutex.release()

        forward.progress_signal.connect(forward_gui.update)
        backward.progress_signal.connect(backward_gui.update)

        forward.finished_signal.connect(lambda success_rate: self.child_inspection_finished(forward_gui, success_rate))
        backward.finished_signal.connect(lambda success_rate: self.child_inspection_finished(backward_gui, success_rate))

    def child_inspection_finished(self, reader, success_rate):
        reader.success_rate = success_rate
        reader.progress_bar.setParent(None)
        reader.label.setParent(None)
        reader.finished = True
        if reader.sibling.finished:
            overall_success_rate = (reader.success_rate + reader.sibling.success_rate) / 2
            text = self.inspection_labels[reader.address].text()
            self.inspection_labels[reader.address].setText(text + " [" + "{:.2f}".format(overall_success_rate * 100) + "% success]")
        
        inspection_gui_manipulation_mutex.acquire()
        del self.current_inspections[reader.id_str]
        inspection_gui_manipulation_mutex.release()
        
        label_list = [] 
        for i in reversed(range(self.inspections_vbox.count())): 
            try:
                widget = self.inspections_vbox.itemAt(i).widget()
                if isinstance(widget, QLabel) and "% success]" in widget.text():
                    label_list.append(widget)
            except AttributeError:
                pass
        label_list = label_list[:5]
        for i in reversed(range(self.inspections_vbox.count())): 
            try:
                widget = self.inspections_vbox.itemAt(i).widget()
                if isinstance(widget, QLabel) and "% success]" in widget.text():
                    if widget in label_list:
                        widget.show()
                        widget.setStyleSheet("")
                    else:
                        widget.setParent(None)
            except AttributeError:
                pass


    @QtCore.pyqtSlot()
    def start(self):

        def validate_hex(inp):
        try:
            if 0 <= int(inp, 16) <= disk_usage(self.selected_vol + ':\\').total:
                self.start_button.setText('...')
                self.start_button.setDisabled(True)
                self.init_address_input.setDisabled(True)
                return int(inp, 16)
            else:
                return None
        except ValueError:
            return None

        user_input = self.init_address_input.text()
        if not user_input:
            self.init_address_input.setText('0x00000000')
            user_input = self.init_address_input.text()
        validated_start_address = validate_hex(user_input)
        if validated_start_address is None:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText(user_input + ' is not a valid address.')
            msg.setInformativeText('Please enter a value between 0x0 and ' \
                + str(hex(disk_usage(self.selected_vol + ':\\').total).upper() + '.'))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()  
            return

        self.skim_progress_bar.setTextVisible(True)
        self.skim_progress_bar.setFormat("Loading...")
        self.skim_progress_bar.setAlignment(QtCore.Qt.AlignCenter)

        self.job = Job(self.selected_vol, self.file, validated_start_address)
        self.job.moveToThread(self.job_thread)

        self.job.success_signal.connect(self.file_gui_update)
        self.job.finished_signal.connect(self.job_finished)
        self.job.test_run_progress_signal.connect(self.skim_progress_bar.setValue)
        self.job.test_run_finished_signal.connect(self.test_run_finished)
        self.job.skim_reader.new_inspection_signal.connect(self.initialize_inspection_gui)
        self.job.skim_reader.progress_signal.connect(self.skim_gui_update)
        self.job.skim_reader.resuming_signal.connect(lambda: self.skim_progress_bar.setTextVisible(False))
        
        self.job_thread.started.connect(self.job.run)
        self.job_thread.start()

    @QtCore.pyqtSlot(tuple)
    def test_run_finished(self, data):
        self.job.skim_reader.perf.new_average_signal.connect(self.new_skim_average)
        self.inspection_sample_size = data[0]
        self.skim_progress_bar.setTextVisible(False)
        self.skim_progress_bar.setFormat(None)
        self.new_skim_average(data[1])
        self.clock.start(1000)

    @QtCore.pyqtSlot(tuple)
    def job_finished(self, data):
        
        success = data[0]
        auto_filled = data[1]

        finished_dialog = QMessageBox()
        finished_dialog.setWindowTitle('recoverability')
        finished_dialog.setIcon(QMessageBox.Warning)
        if success:
            if auto_filled > 0:
                finished_dialog.setText('Finished: output written to ' + self.job.rebuilt_file_path + '\n\n' + str(auto_filled) \
                    + ' meaningless sectors were auto-filled (' + "{:.6f}".format(auto_filled / self.job.total_sectors) \
                    + '%)')
            else:
                finished_dialog.setText('Finished: output written to ' + self.job.rebuilt_file_path + '\n\n' \
                    + 'No meaningless sectors were auto-filled.')
        else:
            finished_dialog.setText('Sorry, your file was not successfully rebuilt. Perhaps your volume is unrecoverable, or you have chosen a file that did not previously exist on the volume.\n\n' + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) + "% of the file was able to be reconstructed using data from this volume.")
        finished_dialog.setStandardButtons(QMessageBox.Ok)
        finished_dialog.exec()

        self.close()

    @QtCore.pyqtSlot(int)
    def file_gui_update(self, i):
        self.rebuilt_file_info.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
        + "%\n\nTesting equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))
        
    @QtCore.pyqtSlot()
    def skim_gui_update(self):
        progress =  self.job.skim_reader.perf.sectors_read
        percent = 100 * progress / self.job.skim_reader.perf.total_sectors_to_read
        self.skim_percentage.setText("{:.8f}".format(percent) + "%")
        self.skim_progress_bar.setValue(percent)
        
