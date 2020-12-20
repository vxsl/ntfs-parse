# Standard library imports
from threading import current_thread
from shutil import disk_usage
import sys
# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, \
                            QLabel, QLineEdit, QPushButton, QCheckBox, \
                            QWidget, QProgressBar, QMessageBox, \
                            QVBoxLayout, QGroupBox

# Local imports
from recreate_file import Job, executor_queue_signal

SECTOR_SIZE = 512
window = None

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


class FinishedDialog(QMessageBox):
    def __init__(self, success, path):
        super().__init__()
        self.setWindowTitle('recoverability')
        self.setIcon(QMessageBox.Warning)
        if success:
            self.setText('Finished: output written to ' + path)
            #TODO display diff of original vs rebuilt
        else:
            self.setText('Unsuccessful.')
            #TODO not sure what to do here
        self.setStandardButtons(QMessageBox.Ok)


class InspectionModel(QtCore.QObject):

    def __init__(self, id_tuple, sector_limit, prefix, estimate_fn):
        super().__init__()
        self.id_str = id_tuple[0] + id_tuple[2]
        self.progress_bar = QProgressBar()
        self.label = QLabel(prefix)
        self.sector_limit = sector_limit
        self.avg = 0
        self.estimate_fn = estimate_fn

    @QtCore.pyqtSlot(tuple)
    def update(self, info):
        sector_count = info[0]
        success_count = info[1]
        self.progress_bar.setValue(100 * sector_count / self.sector_limit)
        if self.avg > 0:
            self.label.setText(str(sector_count) + '/' + str(self.sector_limit) \
                                + '\n' + '{:.4f}'.format(100 * success_count / sector_count) \
                                + "% success")
        else:
            self.label.setText(str(sector_count) + '/' + str(self.sector_limit) \
                                + '\n...\n...')

    def finish(self):
        self.progress_bar.setParent(None)
        self.label.setParent(None)
        del window.current_inspections[self.id_str]

class MainWindow(QWidget):
    def __init__(self, selected_vol, path):
        # TODO remove useless attribute assignments
        global window
        window = self

        super().__init__()
        self.setWindowTitle("recoverability")        

        self.job = None
        
        self.file = SourceFile(path)
        self.selected_vol = selected_vol

        self.file_info_box = QGroupBox("Source file")
        file_info = QGridLayout()
        file_info.addWidget(QLabel('Name:'), 0, 0)
        file_info.addWidget(QLabel(self.file.name), 0, 1)
        file_info.addWidget(QLabel('Location:'), 1, 0)
        file_info.addWidget(QLabel(self.file.dir), 1, 1)
        file_info.addWidget(QLabel('Size:'), 2, 0)
        file_info.addWidget(QLabel(str(len(self.file.remaining_sectors)) + " sectors"), 2, 1)
        self.file_info_box.setLayout(file_info)
        
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
        self.successes.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.successes.setText("0/" + (str(len(self.file.remaining_sectors))))

        self.skim_progress_bar = QProgressBar()
        self.skim_progress_bar.setTextVisible(False)
        self.skim_percentage = QLabel()
        self.sector_avg = QLabel()

        self.time_remaining = QLabel()

        self.current_addr = QPushButton('Display current address in skim')
        self.current_addr.clicked.connect(self.display_current_skim_address)

        self.start_button = QPushButton('Start')
        self.start_button.clicked.connect(self.start)

        #self.main_clock = QtCore.QTimer(self)
        self.time_remaining = QLabel()
        self.time = QtCore.QTime(0, 1, 0)
        self.main_clock = QtCore.QTimer(self)
        self.main_clock.timeout.connect(self.render_main_clock)
        #self.main_clock.timeout.connect(lambda: self.main_clock.setText)

        grid = QGridLayout()
        grid.addWidget(self.file_info_box, 0, 0)

        self.skim_percentage.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.skim_percentage, 6, 2)

        self.sector_avg.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.sector_avg, 9, 2)

        self.time_remaining.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.time_remaining, 8, 2)

        self.executor_queue = QLabel()
        self.executor_queue.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.executor_queue, 10, 2)

        self.current_inspections = {}
        self.current_inspection_averages = {}
        self.current_slowest_inspection = None
        self.inspection_sample_size = None

        self.inspections_box = QGroupBox("Close inspections")
        self.inspections_vbox = QVBoxLayout()
        self.inspections_box.setLayout(self.inspections_vbox)
        grid.addWidget(self.inspections_box, 5, 0, 1, 3)

        grid.addWidget(self.successes, 0, 2)
        grid.addWidget(self.current_addr, 7, 2)
        grid.addWidget(self.skim_progress_bar, 4, 0, 1, 3)

        grid.addWidget(self.start_button, 9, 0)
        grid.addLayout(start_at_hbox, 10, 0)

        self.setLayout(grid)

        current_thread().name = "MAIN GUI THREAD"

    def display_current_skim_address(self):
        if not self.current_inspections:
            self.current_addr.setText(hex(self.job.skim_reader.fobj.tell()))
        else:
            self.current_addr.setText(hex(self.job.skim_reader.fobj.tell()) + ' (paused)')

    def render_main_clock(self):
        if self.current_inspections:
            if self.current_slowest_inspection:
                self.time = self.time.addSecs(-1)                
                the_time = self.time.toString("h:mm:ss")
                self.time_remaining.setText("Average time to parse " \
                    + str(len(self.current_inspections) * self.inspection_sample_size) \
                    + "+ sectors: " + "{:.2f}".format(self.current_slowest_inspection.avg) \
                    + " s\n" + the_time + " remaining to finish all close inspections.\n")
            else:
                self.time_remaining.setText(self.time.toString("h:mm:ss") + \
                    " remaining in skim (paused)... calculating time remaining in close inspection(s).")
        else:
            self.time = self.time.addSecs(-1)                
            the_time = self.time.toString("h:mm:ss")
            self.time_remaining.setText(the_time + " remaining in skim")
            
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

    def new_skim_average(self, data):
        avg = data[0]
        estimate = data[1]
        self.sector_avg.setText("Average time to skim " \
            + str(self.job.skim_reader.perf.sample_size * self.job.skim_reader.perf.jump_size) + " sectors (" \
            + str(self.job.skim_reader.perf.sample_size * self.job.skim_reader.perf.jump_size * 512 / 1000000) \
            + " MB): {:.2f}".format(avg) + " seconds")
        self.time.setHMS(0,0,0)
        self.time = self.time.addSecs(estimate)

    def new_inspection_average(self, data):
        id_str = data[1]
        avg = data[0]

        self.current_inspections[id_str].avg = avg
        self.current_inspection_averages[id_str] = avg
        if len(self.current_inspection_averages) == len(self.current_inspections):
            slowest = max(self.current_inspections, key=lambda x: self.current_inspections[x].avg)
            self.current_slowest_inspection = self.current_inspections[slowest]
            self.time.setHMS(0,0,0)
            self.time = self.time.addSecs(self.current_inspections[slowest].estimate_fn())
            del self.current_inspection_averages
            self.current_inspection_averages = {}

    def initialize_inspection_gui(self, inspection):
        label_prefix = hex(inspection.addr)
        label = QLabel(label_prefix)

        inspection.forward.perf.new_average_signal.connect(self.new_inspection_average)
        inspection.backward.perf.new_average_signal.connect(self.new_inspection_average)

        forward_gui = InspectionModel(inspection.forward.id_tuple, inspection.forward.sector_limit, label_prefix, inspection.forward.perf.get_remaining_estimate)
        backward_gui = InspectionModel(inspection.backward.id_tuple, inspection.backward.sector_limit, label_prefix, inspection.backward.perf.get_remaining_estimate)

        bars = QHBoxLayout()

        # add forward to layout
        box = QVBoxLayout()
        forward_gui.progress_bar.setTextVisible(False)
        box.addWidget(forward_gui.progress_bar)
        box.addWidget(forward_gui.label)
        bars.addLayout(box)

        # add backward to layout
        box = QVBoxLayout()
        backward_gui.progress_bar.setTextVisible(False)
        box.addWidget(backward_gui.progress_bar)
        box.addWidget(backward_gui.label)
        bars.addLayout(box)

        self.inspections_vbox.addWidget(label)
        self.inspections_vbox.addLayout(bars)
        self.inspections_box.setLayout(self.inspections_vbox)

        self.current_inspections[forward_gui.id_str] = forward_gui
        self.current_inspections[backward_gui.id_str] = backward_gui

        inspection.forward.progress_signal.connect(forward_gui.update)
        inspection.backward.progress_signal.connect(backward_gui.update)

        inspection.forward.finished_signal.connect(forward_gui.finish)
        inspection.backward.finished_signal.connect(backward_gui.finish)

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
                self.start_button.setText('...')
                self.start_button.setDisabled(True)
                self.start_at.setDisabled(True)
                return int(inp, 16)
            else:
                return None
        except ValueError:
            return None

    def start(self):

        user_input = self.start_at.text()
        validated_start_address = self.validate_hex(user_input)
        if validated_start_address is None:
            self.invalid_address(user_input, self.selected_vol)
            return

        self.skim_progress_bar.setTextVisible(True)
        self.skim_progress_bar.setFormat("Loading...")
        self.skim_progress_bar.setAlignment(QtCore.Qt.AlignCenter)

        self.job_thread = QtCore.QThread()
        self.job = Job(self.selected_vol, self.file, SECTOR_SIZE, validated_start_address)
        self.job.moveToThread(self.job_thread)

        executor_queue_signal.connect(lambda num: self.executor_queue.setText(str(num) + " sectors in the queue"))
        self.job.success_signal.connect(self.file_gui_update)
        self.job.finished_signal.connect(self.finished)
        self.job.perf_created_signal.connect(lambda: self.job.skim_reader.perf.new_average_signal.connect(self.new_skim_average))
        self.job.skim_reader.resumed_signal.connect(self.resume_skim_gui)
        self.job.skim_reader.new_inspection_signal.connect(self.initialize_inspection_gui)
        self.job.skim_reader.progress_signal.connect(self.skim_gui_update)

        self.job.loading_progress_signal.connect(self.skim_progress_bar.setValue)
        self.job.loading_complete_signal.connect(self.loading_finished)
        
        self.job_thread.started.connect(self.job.run)
        self.job_thread.start()

    def loading_finished(self, data):
        self.inspection_sample_size = data[0]
        self.skim_progress_bar.setTextVisible(False)
        self.skim_progress_bar.setFormat(None)
        self.new_skim_average(data[1])
        self.main_clock.start(1000)

    def finished(self, success):
        FinishedDialog(success, self.job.rebuilt_file_path).exec()
        self.close()

    def file_gui_update(self, i):
        self.job.done_sectors += 1
        self.successes.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
        + "%\n\nTesting equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))

    def resume_skim_gui(self):        
        #self.inspections_vbox.setParent(None)
        self.inspections_box.hide()
        """ for i in reversed(range(self.inspections_vbox.count())): 
            self.inspections_vbox.itemAt(i).widget().setParent(None) """

        
    def skim_gui_update(self):
        progress =  self.job.skim_reader.perf.sectors_read
        percent = 100 * progress / self.job.skim_reader.perf.total_sectors_to_read
        self.skim_percentage.setText("{:.8f}".format(percent) + "%")
        self.skim_progress_bar.setValue(percent)
        
