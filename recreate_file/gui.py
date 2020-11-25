from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from math import ceil
from datetime import timedelta
import re
from .recreate_file import *

class ChooseReferenceFileDialog(QFileDialog):
    def __init__(self):
        super(ChooseReferenceFileDialog, self).__init__()
        self.setWindowTitle("choose reference file")

class MainWindow(QWidget):
    def __init__(self, selected_vol):
        super().__init__()          

        dlg = ChooseReferenceFileDialog()
        dlg.exec()
        path = dlg.selectedFiles()[0]

        reference_file = ReferenceFile(path)

        file_info_grid = QGridLayout()
        file_info_grid.addWidget(QLabel('File name:'), 0, 0)        
        file_info_grid.addWidget(QLabel(reference_file.name), 0, 1)
        file_info_grid.addWidget(QLabel('Directory:'), 1, 0)
        file_info_grid.addWidget(QLabel(reference_file.dir), 1, 1)
        file_info_grid.addWidget(QLabel('Size:'), 2, 0)        
        file_info_grid.addWidget(QLabel(str(ceil((reference_file.size / 512))) + " sectors"), 2, 1)        

        start_at_hbox = QHBoxLayout()
        start_at_label = QLabel("Start at address (search forward): ")
        self.start_at = QLineEdit()
        #self.start_at.setText('0x404A8A99000')
        self.start_at.setText('0x404c91a1800')
        start_at_hbox.addWidget(start_at_label)
        start_at_hbox.addWidget(self.start_at)

        successes_hbox = QHBoxLayout()        
        self.successes = QLabel()
        self.successes.setText("0/" + (str(ceil((reference_file.size / 512)))))
        successes_hbox.addWidget(self.successes)

        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(False)
        self.start = QPushButton('Start')
        self.progressPercentage = QLabel()
        self.sector_avg = QLabel()
        self.time_remaining = QLabel()

        self.express_mode = QCheckBox("Express mode (only disable for small disks): ")
        self.express_mode.setChecked(True) 
        self.do_logging = QCheckBox("Log (./ntfs-toolbox/...): ")
        self.do_logging.setChecked(False)
        
        self.current_addr = QPushButton('Display current address')
        self.current_addr.clicked.connect(lambda: self.current_addr.setText(hex(self.job.primary_reader.fd.tell())))
   
        self.start.clicked.connect(lambda: self.go(selected_vol, reference_file))

        grid = QGridLayout()        
        grid.addLayout(file_info_grid, 0, 0)

        grid.addWidget(self.express_mode, 7, 0)         
        grid.addWidget(self.do_logging, 8, 0)   

        self.progressPercentage.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.progressPercentage, 6, 2)
        
        self.sector_avg.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.sector_avg, 9, 2)

        self.time_remaining.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)         
        grid.addWidget(self.time_remaining, 8, 2)

        grid.addLayout(successes_hbox, 3, 0)        
        grid.addWidget(self.current_addr, 7, 2)
        grid.addWidget(self.progressBar, 4, 0, 4, 3)      
        grid.addWidget(self.start, 9, 0)
        grid.addLayout(start_at_hbox, 10, 0) 
        
        self.setLayout(grid)       

    def go(self, selected_vol, reference_file):

        start_at_input = self.start_at.text()
        if re.search('^0x\d+', start_at_input) == None:
            print('not correct pattern')
            return

        self.job = initialize_job(self.do_logging, self.express_mode.isChecked(), selected_vol, reference_file)

        self.job.primary_reader.progress_update.connect(self.visualize_read_progress)
        self.job.success_update.connect(self.updateSuccessCount)
        
        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)  
        self.express_mode.setDisabled(True)
        self.do_logging.setDisabled(True)

        recreate_main = Thread(name='recreate main',target=self.job.primary_reader.read,args=[self.start_at.text().split("x")[1]])

        self.job.perf.start()
        recreate_main.start() 
        # ...
        #recreate_main.join()
        #print("Program terminated")

    def updateSuccessCount(self, i):

        self.job.done_sectors += 1
        
        s = ("Last match: sector " + str(i) + "\n\n")
        s += (str(self.job.done_sectors) + "/" + str(self.job.total_sectors) + " = " + "{:.4f}".format(self.job.done_sectors / self.job.total_sectors) + "%\n\n")
        s += ("Testing equality for " + str(self.job.total_sectors - self.job.done_sectors) + " remaining sectors...")
        self.successes.setText(s)
        
    def visualize_read_progress(self, progress):
        percent = 100 * progress / self.job.diskSize.total
        self.progressPercentage.setText("{:.7f}".format(percent) + "%")
        self.progressBar.setValue(percent)     
        
        if self.job.perf.avg > 0:
            self.sector_avg.setText("Average time to traverse " + str(self.job.perf.sample_size) + " sectors (" + str(self.job.perf.sample_size * 512 / 1000000) + " MB): {:.2f}".format(self.job.perf.avg) + " seconds")
            self.time_remaining.setText(self.get_remaining_estimate(progress))

    def get_remaining_estimate(self, progress):
        seconds = self.job.perf.avg * ((self.job.diskSize.total - progress) / (512 * self.job.perf.sample_size))        
        return str(timedelta(seconds=seconds)).split(".")[0] + " remaining"