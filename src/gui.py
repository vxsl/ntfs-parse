# Standard library imports
from threading import current_thread, Lock
from shutil import disk_usage
from multiprocessing import cpu_count
import time
import sys
# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, \
                            QLabel, QLineEdit, QPushButton, \
                            QWidget, QProgressBar, QMessageBox, \
                            QVBoxLayout, QGroupBox, QGraphicsScene, \
                            QGraphicsProxyWidget, QGraphicsView

# Local imports
from recoverability import Job, Worker, SECTOR_SIZE, SAMPLE_WINDOW

threadpool = QtCore.QThreadPool.globalInstance()
threadpool.setMaxThreadCount(cpu_count() - 3)
inspection_gui_manipulation_mutex = Lock()

class SourceFile():
    """represents information about the user's selected file that is relevant to both the UI and the main program."""
    def __init__(self, path):
        # the remaining sectors list will start as a list where each element represents a sector in the source file.
        self.remaining_sectors = self.to_sectors(path)

        # the address table will start as a list of empty lists
        self.address_table = [[] for _ in range(len(self.remaining_sectors))]

        # separate path into file and location
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def to_sectors(self, path):
        """
        splits the source file into a list of sectors

        Args:
            path (string): path to the source file

        Returns:
            list:   each element represents SECTOR_SIZE bytes
                    (i.e. one sector) of the source file. The final sector
                    is padded with zeroes to maintain uniform size.
        """
        fobj = open(path, "rb")
        fobj.seek(0)
        result = []
        while True:
            # read SECTOR_SIZE bytes
            cur = fobj.read(SECTOR_SIZE)
            if cur == b'':
                # finish at EOF
                break
            elif len(cur) == SECTOR_SIZE:
                # populate list with an element representing SECTOR_SIZE bytes 
                result.append(cur)
            else:      
                # zfill for final sector -- to achieve uniform sector length even
                # when the data is less than SECTOR_SIZE          
                result.append(\
                (bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1]))))  
        return result

class ChildInspection(QtCore.QObject):
    """Represents information relevant to the UI about a close inspection taking place in the main program"""
    def __init__(self, id_tuple, sector_limit, average_fn, seconds_fn):
        """Construct a ChildInspection object.

        Args:
            id_tuple (tuple):   first element is a string describing the direction of the child inspection ("forward" or "backward") 
                                second element is the decimal midpoint of the parent inspection (int)
                                third element is the same address in hexidecimal (string)
            sector_limit (int): the total number of sectors that the child inspection will read before stopping
            seconds_fn (callable): this will be a pointer to some InspectionPerformanceCalc object's get_remaining_seconds() method.
                                    in order to call this function only on the slowest child inspection, it is stored as a member so that this
                                    evaluation may be made later, once the slowest object in current_inspections is determined. 
        """        
        super().__init__()

        # identification
        self.address = id_tuple[2]
        self.id_str = id_tuple[0] + id_tuple[2]
        
        # gui
        self.label = QLabel(id_tuple[2])
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)

        # logic
        self.new_avg_flag = False
        self.finished = False
        self.sibling = None
        self.sector_limit = sector_limit
        self.avg = 0
        self.average_fn = average_fn
        self.seconds_fn = seconds_fn  

    @QtCore.pyqtSlot(tuple)
    def update(self, info):
        """update information about the close inspection taking place in the main program.

        Args:
            info (tuple): info[0] indicates portion of sectors read, info[1] indicates sectors matched
        """
        # update the child inpsection's progress bar
        self.progress_bar.setValue(100 * info[0])

        # update the child inspection's info text, ex.
        # "1023/42423 sectors
        # 97.7531% success"
        self.label.setText('{:.3f}'.format(100 * info[0]) + '% complete' \
                            + '\n' + '{:.3f}'.format(100 * info[1]) \
                            + "% success")

class MainWindow(QWidget):

    request_skim_average_signal = QtCore.pyqtSignal()

    """
    This is the entrypoint and GUI for the main program.
    Incorporates information regarding the source file, the overall skim,
    and any close inspections that may be occurring. One input field to set
    the address at which to begin the search.
    """
    def __init__(self, selected_vol, path):
        """
        Main window constructor. Create all required widgets and layouts, then
        add to the main layout.

        Args:
            selected_vol (string): the user's selected volume
            path (string): path to the source file
        """
        super().__init__()
        self.setWindowTitle("recoverability")

        # create QThread for main program, to be started later
        self.job_thread = QtCore.QThread()
        self.job = None

        # store information from previous dialog
        self.file = SourceFile(path)
        self.selected_vol = selected_vol

        # begin creating UI elements. Those that will need to be accessed or modified elsewhere in the program
        # are stored as attributes to the MainWindow object.

        # create and populate the "Source file" group box
        source_file_box = QGroupBox("Source file")
        source_file_grid = QGridLayout()
        source_file_grid.addWidget(QLabel('Name:'), 0, 0)
        source_file_grid.addWidget(QLabel(self.file.name), 0, 1)
        source_file_grid.addWidget(QLabel('Location:'), 1, 0)
        source_file_grid.addWidget(QLabel(self.file.dir), 1, 1)
        source_file_grid.addWidget(QLabel('Size:'), 2, 0)
        source_file_grid.addWidget(QLabel(str(len(self.file.remaining_sectors)) + " sectors"), 2, 1)
        source_file_box.setLayout(source_file_grid)

        # create and populate the "Reconstructed file" group box
        reconstructed_file_box = QGroupBox("Reconstructed file")
        reconstructed_file_hbox = QHBoxLayout()
        self.reconstructed_file_info = QLabel()
        self.reconstructed_file_info.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.reconstructed_file_info.setText(("No matches yet\n\n") \
        + ("0/" + (str(len(self.file.remaining_sectors))) \
        + " = " + "0.00%" \
        + "\n\nTesting equality for " + (str(len(self.file.remaining_sectors))) \
        + " remaining sectors..."))
        reconstructed_file_hbox.addWidget(self.reconstructed_file_info)
        reconstructed_file_box.setLayout(reconstructed_file_hbox)

        # place the previous two group boxes next to each other in an Hbox
        files_row = QHBoxLayout()
        files_row.addWidget(source_file_box)
        files_row.addWidget(reconstructed_file_box)

        # create and populate the "Skim" group box
        skim_box = QGroupBox("Skim")
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
        skim_box.setLayout(skim_grid)

        # create and populate the performance information near the bottom of the window.
        self.sector_average = QLabel()
        self.time = QtCore.QTime(0, 0, 0)
        self.time_label = QLabel()
        self.clock = QtCore.QTimer(self)
        self.clock.timeout.connect(self.draw_clock)

        # create and populate the "Close inspections" group box, which will initially be hidden from view
        self.inspections_box = QGroupBox("Close inspections")
        self.inspections_vbox = QVBoxLayout()
        self.inspections_box.setLayout(self.inspections_vbox)
        self.inspections_box.hide()
        self.inspection_labels = {}

        # prepare inspection logic
        self.current_inspections = {}
        self.current_slowest_inspection = None
        
        # create and populate the final row, with a start button and hex input
        start_hbox = QHBoxLayout()
        self.start_button = QPushButton('Start')
        self.start_button.clicked.connect(self.start)
        self.init_address_input = QLineEdit()
        self.init_address_input.setPlaceholderText('Begin at address (default 0x0000000000)')
        init_address_hbox = QHBoxLayout()
        init_address_hbox.addWidget(self.init_address_input)
        start_hbox.addLayout(init_address_hbox)
        start_hbox.addWidget(self.start_button)

        # add all above widgets and layouts to an overall grid
        grid = QGridLayout()
        grid.addLayout(files_row, 0, 0)
        grid.addWidget(skim_box, 4, 0)
        grid.addWidget(self.inspections_box, 5, 0)
        grid.addWidget(self.sector_average, 7, 0)
        grid.addWidget(self.time_label, 8, 0)
        grid.addLayout(start_hbox, 9, 0)
        
        # overall layout options        
        grid.setSpacing(50)
        grid.setContentsMargins(50, 50, 50, 50)
        self.setLayout(grid)

        self.cur_secs = 0

    @QtCore.pyqtSlot()
    def display_current_skim_address(self):
        """
        Display the address of the most recently read sector during the overall skim.
        If the skim is paused, (paused) is concatenated to the output.
        """
        # TODO create blocking condition for rapid clicks
        if hasattr(self, 'job'):
            if not self.current_inspections:
                self.skim_address_button.setText(hex(self.job.skim_reader.fobj.tell()))
            else:
                self.skim_address_button.setText(hex(self.job.skim_reader.fobj.tell()) + ' (paused)')
        else:
            self.skim_address_button.setText("Skim has not been started.")

        # QTimer singleshot resets button text after 2 seconds
        QtCore.QTimer.singleShot(2000, lambda: self.skim_address_button.setText('Display current address in skim'))

    def request_averages(self):
        """.. . . . . ..  . and Update skim performance statistics in the main window
        """        
        if not self.current_inspections:
            data = self.job.skim_reader.perf.calculate_average()
            # first element is a float representing an average skimming time for some interval.
            # second element is an int representing the estimated skim time remaining based on this average.
            avg = data[0] * self.job.jump_sectors
            estimate = data[1]
            self.sector_average.setText("Average sectors skimmed per " + str(SAMPLE_WINDOW) + " seconds: "
                + str(int(avg)) + '\n(' + str(int(data[0])) + ' read)')
            self.time.setHMS(0,0,0)
            self.time = self.time.addSecs(estimate)
            
            return

        inspection_gui_manipulation_mutex.acquire()

        for key in self.current_inspections:
            insp = self.current_inspections[key]
            insp.avg = insp.average_fn()
            
        # now that fresh averages have been collected for all current inspections,
        # determine the slowest inspection
        slowest_id = max(self.current_inspections, key=lambda x: self.current_inspections[x].avg)
        self.current_slowest_inspection = self.current_inspections[slowest_id]

        # get the estimated seconds remaining in that inspection 
        secs_remaining = self.current_slowest_inspection.seconds_fn()

        # quit if no estimate is possible yet
        if secs_remaining == 0:
            return
    
        # update time remaining by resetting to 0 then adding the new estimate
        self.time.setHMS(0,0,0)
        try:
        self.time = self.time.addSecs(secs_remaining)
        except:
            pass
        inspection_gui_manipulation_mutex.release()


    @QtCore.pyqtSlot()
    def draw_clock(self):
        """
        Draw the "time remaining" timer. This method is called once every second.
        Output corresponds to the overall skim or to the collection of
        current close inspections, as appropriate.
        """
        self.cur_secs += 1
        if self.cur_secs >= SAMPLE_WINDOW:
            self.cur_secs = 0
            threadpool.start(Worker(self.request_averages))           
            
        if self.current_inspections:
            if self.current_slowest_inspection:
                self.time = self.time.addSecs(-1)
                the_time = self.time.toString("h:mm:ss")
                self.time_label.setText("Average sectors parsed in " + \
                    str(SAMPLE_WINDOW) + " seconds: " + \
                    "{:.2f}".format(self.current_slowest_inspection.avg) + \
                    "\n" + the_time + " remaining to finish current close inspections.\n")
            else:
                self.time_label.setText(self.time.toString("h:mm:ss") + \
                    " remaining in skim (paused)... calculating time remaining in close inspection(s).")
        else:
            self.time = self.time.addSecs(-1)
            the_time = self.time.toString("h:mm:ss")
            self.time_label.setText(the_time + " remaining in skim")

    def closeEvent(self, event):
        """Overridden method to warn the user about closing the window while still in progress."""
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
    def initialize_inspection_gui(self, data):
        """Create and initialize two new progress bars representing close inspections in the program.

        Args:
            data (tuple):   the first element is an int representing the decimal address of the close inspection's midpoint.
                            the second and third elements are CloseReader objects passed from the main program. Attributes relevant
                            to the UI are extracted, and the objects' signals are dynamically connected to the appropriate slots.
        """
        address = data[0]
        forward = data[1]
        backward = data[2]

        self.skim_progress_bar.setTextVisible(True)
        self.skim_progress_bar.setFormat("Paused")

        forward_gui = ChildInspection(forward.id_tuple, forward.sector_limit, forward.perf.calculate_average, forward.perf.get_remaining_seconds)
        backward_gui = ChildInspection(backward.id_tuple, backward.sector_limit, backward.perf.calculate_average, backward.perf.get_remaining_seconds)

        forward_gui.sibling = backward_gui
        backward_gui.sibling = forward_gui

        bars = QHBoxLayout()

        # add forward to layout
        box = QVBoxLayout()
        box.addWidget(backward_gui.progress_bar)
        box.addWidget(backward_gui.label)
        bars.addLayout(box)

        # add forward to layout
        box = QVBoxLayout()
        box.addWidget(forward_gui.progress_bar)
        box.addWidget(forward_gui.label)
        bars.addLayout(box)

        self.inspection_labels[hex(address)] = QLabel(hex(address))
        self.inspection_labels[hex(address)].setStyleSheet("font-weight: bold")
        self.inspections_vbox.addWidget(self.inspection_labels[hex(address)])
        self.inspections_vbox.addLayout(bars)
        self.inspections_box.show()

        self.current_inspections[forward_gui.id_str] = forward_gui
        self.current_inspections[backward_gui.id_str] = backward_gui

        forward.progress_signal.connect(forward_gui.update)
        backward.progress_signal.connect(backward_gui.update)

        forward.finished_signal.connect(lambda success_rate: self.child_inspection_finished(forward_gui, success_rate))
        backward.finished_signal.connect(lambda success_rate: self.child_inspection_finished(backward_gui, success_rate))

    def child_inspection_finished(self, reader, success_rate):
        inspection_gui_manipulation_mutex.acquire()
        reader.success_rate = success_rate
        reader.progress_bar.setParent(None)
        reader.label.setParent(None)
        reader.finished = True
        if reader.sibling.finished:
            overall_success_rate = (reader.success_rate + reader.sibling.success_rate) / 2
            text = self.inspection_labels[reader.address].text()
            self.inspection_labels[reader.address].setText(text + " [completed, " + "{:.2f}".format(overall_success_rate * 100) + "% success]")

        del self.current_inspections[reader.id_str]
        inspection_gui_manipulation_mutex.release()

        label_list = []
        for i in reversed(range(self.inspections_vbox.count())):
            try:
                widget = self.inspections_vbox.itemAt(i).widget()
                if isinstance(widget, QLabel) and "completed" in widget.text():
                    label_list.append(widget)
            except AttributeError:
                pass
        label_list = label_list[:5]
        for i in reversed(range(self.inspections_vbox.count())):
            try:
                widget = self.inspections_vbox.itemAt(i).widget()
                if isinstance(widget, QLabel) and "completed" in widget.text():
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
            # TODO check for valid fobj seek with addr
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
            self.init_address_input.setText('0x3982113c00')
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
        """Carry out initialization tasks that require completion of the main program's "test run".

        Args:
            data (tuple):   the first element is the inspection sample size, dependent on the size of the source file.
                            the second element is the projected skim average.
        """
        self.skim_progress_bar.setTextVisible(False)
        self.skim_progress_bar.setFormat(None)
        #self.new_skim_average(data)
        self.cur_secs = 6
        self.clock.start(1000)
    
    @QtCore.pyqtSlot(tuple)
    def job_finished(self, data):
        """Display a dialog with final statistics about the main program's execution, then exit.

        Args:
            data (tuple):   the first element represents the boolean success of the main program.
                            the second element represents the number of meaningless sectors that were "auto-filled"
                            by the main program in the final reconstruction of the source file.
        """
        self.showNormal()
        self.showMinimized()
        success = data[0]
        auto_filled = data[1]

        finished_dialog = QMessageBox()
        finished_dialog.setWindowTitle('recoverability')
        finished_dialog.setIcon(QMessageBox.Warning)
        if success:
            text = 'Finished: output written to ' + self.job.rebuilt_file_path + '\n\n'
            if auto_filled > 0:
                text += str(auto_filled) + ' meaningless sectors were auto-filled (' \
                    + "{:.6f}".format(auto_filled / self.job.total_sectors) \
                    + '%)'
            else:
                text += 'No meaningless sectors were auto-filled.'
        else:
            text = 'Sorry, your file was not successfully rebuilt. Perhaps your volume is unrecoverable, ' \
                    + 'or you have chosen a file that did not previously exist on the volume.\n\n' \
                    + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
                    + "% of the file was able to be reconstructed using sectors from this volume."
        finished_dialog.setText(text)
        finished_dialog.setStandardButtons(QMessageBox.Ok)
        finished_dialog.exec()

        self.close()

    @QtCore.pyqtSlot(int)
    def file_gui_update(self, i):
        """Update information shown in the "Reconstructed file" area of the main window.

        Args:
            i (int): last matched sector of source file
        """
        self.reconstructed_file_info.setText(("Last match: sector " + str(i) + "\n\n") \
        + (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) \
        + " = " + "{:.2f}".format(100 * self.job.done_sectors / self.job.total_sectors) \
        + "%\n\nTesting equality for " + str(self.job.total_sectors - self.job.done_sectors) \
        + " remaining sectors..."))

    @QtCore.pyqtSlot(float)
    def skim_gui_update(self, progress):
        """Update information shown in the "Skim" area of the main window."""
        percent = 100 * progress
        self.skim_percentage.setText("{:.8f}".format(percent) + "%")
        self.skim_progress_bar.setValue(percent)

