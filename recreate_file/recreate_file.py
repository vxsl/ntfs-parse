import time, os, re, copy
from shutil import disk_usage
from .performance.performance import PerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread, Lock
from concurrent import futures
from multiprocessing import cpu_count
from math import ceil
from datetime import timedelta


def check_sector(inp, addr):
#def check_sector():
    for b in reader.reference_file.sectors:
        if inp == b:
            i = reader.reference_file.sectors.index(b)
            reader.rebuilt[i] = (addr, copy.deepcopy(b))
            reader.successUpdate.emit(i)
            reader.log.write(str(addr) + "\t\t" + str(i) + "\n")
            reader.log.flush()
            print("check_sector: sector at logical address " + str(addr) + " on disk is equal to sector " + str(i) + " of reference file.")
            if i+1 == len(reader.reference_file.sectors):
                reader.finished = True
            reader.reference_file.sectors.remove(b)
            return
    return

def recreate(start_at):

    executor = futures.ThreadPoolExecutor(max_workers=(cpu_count())) # TODO what is the correct number here? Surely it is not correct to take all available threads..?

    # start position in bytes
    reader.diskFd.seek(int(start_at, 16))
    reader.perf.start()
    # main loop
    while not reader.finished:
        executor.submit(check_sector, reader.diskFd.read(512), hex(reader.diskFd.tell() - 512))
        reader.progressUpdate.emit([reader.diskFd.tell(), reader.perf.avg])        
        reader.perf.increment()
        #reader.diskFd.seek((len(reader.rebuilt) * 512), 1) # TODO 512 = ALLOCATION_UNIT

class DiskReader(QtCore.QObject):    
    
    # PyQt event signallers
    progressUpdate = QtCore.pyqtSignal(object)
    successUpdate = QtCore.pyqtSignal(object)

    def __init__(self, vol, reference_file):
        super().__init__()
        self.diskPath = r"\\." + "\\" + vol + ":"   
        disk = os.open(self.diskPath, os.O_RDONLY | os.O_BINARY)
        self.diskFd = os.fdopen(disk, 'rb')
        self.diskSize = disk_usage(vol + ':\\')
        self.perf = PerformanceCalc(self.diskFd)
        self.successCount = [0, 0]
        self.reference_file = reference_file
        self.rebuilt = [None] * len(reference_file.sectors) 
        self.finished = False

        #create required directories
        dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
        os.makedirs(dir_name, mode=0o755)

        self.log = open(dir_name + '/' + self.reference_file.name + ".log", 'w')
        #self.main(start_at)


class ReferenceFile():
    def __init__(self, path):
        split = path.split('/')
        self.fd = open(path, "rb")
        self.sectors = self.to_sectors(self.fd)
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
        self.start_at.setText('0x404A8A99000')
        #self.start_at.setText('0x404C7A99000')
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

        global reader
        reader = DiskReader(selected_vol, reference_file)
        self.start.clicked.connect(self.go)

        grid = QGridLayout()        
        grid.addLayout(file_info_grid, 0, 0)

        self.progressPercentage.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.progressPercentage, 7, 2)
        
        self.sector_avg.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        grid.addWidget(self.sector_avg, 9, 2)

        self.time_remaining.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)         
        grid.addWidget(self.time_remaining, 8, 2)

        grid.addLayout(successes_hbox, 3, 0)        
        grid.addWidget(self.progressBar, 4, 0, 4, 3)       
        grid.addWidget(self.start, 9, 0)
        grid.addLayout(start_at_hbox, 10, 0) 

        self.setLayout(grid)       

    def go(self):
        
        start_at_input = self.start_at.text()
        if re.search('^0x\d+', start_at_input) == None:
            print('not correct pattern')
            return
        reader.progressUpdate.connect(self.updateProgress)
        reader.successUpdate.connect(self.updateSuccessCount)
     
        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)  
        recreate_main = Thread(name='recreate main',target=recreate,args=[self.start_at.text().split("x")[1]])
        recreate_main.start() 
        # ...
        #recreate_main.join()
        #print("Program terminated")

    def updateSuccessCount(self, i):
        successCount = 0 
        for entry in reader.rebuilt:
            if entry != None:
                successCount += 1
        
        s = ("Last match: sector " + str(i) + "\n\n")
        s += (str(successCount) + "/" + str(len(reader.rebuilt)) + " = " + "{:.4f}".format(successCount / len(reader.rebuilt)) + "%\n\n")
        s += ("Checking equality for " + str(len(reader.reference_file.sectors)) + " remaining sectors...")
        self.successes.setText(s)
        
    def updateProgress(self, progress):
        percent = 100 * progress[0] / reader.diskSize.total
        self.progressPercentage.setText("{:.7f}".format(percent) + "%")
        self.sector_avg.setText("Average time to read and parse " + str(reader.perf.sample_size) + " sectors (" + str(reader.perf.sample_size * 512 / 1000000) + " MB): {:.2f}".format(progress[1]) + " seconds")
        self.progressBar.setValue(percent)     
        self.time_remaining.setText(self.get_remaining_estimate(progress))

    def get_remaining_estimate(self, progress):
        seconds = reader.perf.avg * ((reader.diskSize.total - progress[0]) / (512 * reader.perf.sample_size))
        return str(timedelta(seconds=seconds)).split(".")[0] + " remaining"