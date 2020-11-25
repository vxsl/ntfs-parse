import time, os, re, copy
from shutil import disk_usage
from .performance.performance import PerformanceCalc, ExpressPerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread, Lock
from concurrent import futures
from multiprocessing import cpu_count
from math import ceil
from datetime import timedelta
import cProfile, pstats, io ##

lock = Lock()

def check_sector(inp, addr, already_in_close_inspection=False):
    for sector in job.reference_file.remaining_sectors:
        if inp == sector and (addr, sector) not in job.rebuilt_file:
            addr = hex(addr - 512)
            with lock:
                i = job.reference_file.sectors.index(sector)
                job.rebuilt_file[i] = (addr, copy.deepcopy(sector))       
                job.reference_file.remaining_sectors.pop(job.reference_file.remaining_sectors.index(sector))            
            job.success_update.emit(i)
            job.log.write(str(addr) + "\t\t" + str(i) + "\n")
            job.log.flush()
            print("check_sector: sector at logical address " + addr + " on disk is equal to sector " + str(i) + " of reference file.")            
            if not already_in_close_inspection:
                close_inspect(addr)
            return
    return

def close_inspect(addr):
    fwd = ForwardCloseReader()
    bkwd = BackwardCloseReader()
    job.readers.append(fwd)
    job.readers.append(bkwd)
    Thread(name='close inspect forward @' + addr,target=fwd.read,args=[addr]).start()
    Thread(name='close inspect backward @' + addr,target=bkwd.read,args=[addr]).start()

class DiskReader(QtCore.QObject):
    
    def __init__(self):
        super().__init__()
        self.fd = os.fdopen(os.open(job.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):
    def __init__(self):
        super().__init__()
        self.sector_limit = (job.total_sectors * 6) #??? 

class ForwardCloseReader(CloseReader):
    def __init__(self):
        super().__init__()

    def read(self, addr):
        self.sector_count = 0
        self.fd.seek(int(addr, 16))
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(512), self.fd.tell(), True)

class BackwardCloseReader(CloseReader):
    def __init__(self):
        super().__init__()
    def read(self, addr):
        self.sector_count = 0
        self.fd.seek(int(addr, 16))
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(512), self.fd.tell(), True)
            self.fd.seek(-1024, 1)


class PrimaryReader(DiskReader):

    progress_update = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()

    def read(self, addr):
        """ pr = cProfile.Profile()
        pr.enable()  # start profiling """

        self.fd.seek(int(addr, 16))
        executor = futures.ThreadPoolExecutor(thread_name_prefix="Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(512), self.fd.tell())
            self.progress_update.emit(self.fd.tell())
            job.perf.increment()

        """ pr.disable()  # end profiling
        sortby = 'cumulative'
        ps = pstats.Stats(pr, stream=io.StringIO).sort_stats(sortby)
        ps.print_stats() """
            

class ExpressPrimaryReader(PrimaryReader):

    progress_update = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        
    def read(self, addr):
        self.fd.seek(int(addr, 16))
        executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(512), self.fd.tell())
            self.progress_update.emit(self.fd.tell())        
            job.perf.increment()
            self.fd.seek(((job.total_sectors//2) * 512), 1) # TODO 512 = ALLOCATION_UNIT
            
class Job(QtCore.QObject):    

    # PyQt event signallers
    success_update = QtCore.pyqtSignal(object)

    def __init__(self, vol, reference_file, do_logging, express):
        super().__init__()
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"   
        self.diskSize = disk_usage(vol + ':\\')
        self.reference_file = reference_file
        self.finished = False
        self.done_sectors = 0
        self.total_sectors = len(reference_file.sectors)         
        self.rebuilt_file = [None] * self.total_sectors
        self.readers = []
        #self.readers.append(DiskReader(self.disk_path))
        
        if do_logging == True:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.reference_file.name + ".log", 'w')
        else:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.reference_file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")


class ReferenceFile():
    def __init__(self, path):
        split = path.split('/')
        self.fd = open(path, "rb")
        self.sectors = self.to_sectors(self.fd)
        self.remaining_sectors = copy.deepcopy(self.sectors)
        self.size = os.stat(path).st_size
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def to_sectors(self, file):
        file.seek(0)
        result = []
        while True:
            cur = file.read(512)
            if cur == b'':
                break
            elif len(cur) == 512:
                result.append(cur)
            else:
                result.append((bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])), False))   #trailing sector zfill
        return result


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
        self.current_addr.clicked.connect(lambda: self.current_addr.setText(hex(job.primary_reader.fd.tell())))
   
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

        global job
        if self.express_mode.isChecked():
            job = Job(selected_vol, reference_file, self.do_logging.isChecked(), True)
            job.primary_reader = ExpressPrimaryReader()
            job.perf = ExpressPerformanceCalc(job.total_sectors)
        else:
            job = Job(selected_vol, reference_file, self.do_logging.isChecked(), False)
            job.primary_reader = PrimaryReader()            
            job.perf = PerformanceCalc()

        job.primary_reader.progress_update.connect(self.visualize_read_progress)
        job.success_update.connect(self.updateSuccessCount)
        
        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)  
        self.express_mode.setDisabled(True)
        self.do_logging.setDisabled(True)

        recreate_main = Thread(name='recreate main',target=job.primary_reader.read,args=[self.start_at.text().split("x")[1]])

        job.perf.start()
        recreate_main.start() 
        # ...
        #recreate_main.join()
        #print("Program terminated")

    def updateSuccessCount(self, i):

        job.done_sectors += 1
        
        s = ("Last match: sector " + str(i) + "\n\n")
        s += (str(job.done_sectors) + "/" + str(job.total_sectors) + " = " + "{:.4f}".format(job.done_sectors / job.total_sectors) + "%\n\n")
        s += ("Testing equality for " + str(job.total_sectors - job.done_sectors) + " remaining sectors...")
        self.successes.setText(s)
        
    def visualize_read_progress(self, progress):
        percent = 100 * progress / job.diskSize.total
        self.progressPercentage.setText("{:.7f}".format(percent) + "%")
        self.progressBar.setValue(percent)     
        
        if job.perf.avg > 0:
            self.sector_avg.setText("Average time to traverse " + str(job.perf.sample_size) + " sectors (" + str(job.perf.sample_size * 512 / 1000000) + " MB): {:.2f}".format(job.perf.avg) + " seconds")
            self.time_remaining.setText(self.get_remaining_estimate(progress))

    def get_remaining_estimate(self, progress):
        seconds = job.perf.avg * ((job.diskSize.total - progress) / (512 * job.perf.sample_size))        
        return str(timedelta(seconds=seconds)).split(".")[0] + " remaining"