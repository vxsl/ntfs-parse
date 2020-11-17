import time, os, re, copy
from shutil import disk_usage
from .performance.performance import PerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread, Lock


class DiskReader(QtCore.QObject):    
    
    # PyQt event signallers
    progressUpdate = QtCore.pyqtSignal(object)
    successUpdate = QtCore.pyqtSignal(object)

    def check_sector(self, inp, addr):
        for b in self.reference_file.sectors:
            if inp == b:
                i = self.reference_file.sectors.index(b)
                self.rebuilt[i] = (addr, copy.deepcopy(b))
                self.successUpdate.emit(i)
                self.log.write(str(addr) + "\t\t" + str(i) + "\n")
                self.log.flush()
                print("check_sector: sector at address " + str(addr) + " on disk is equal to sector " + str(i) + " of reference file.")
                if i+1 == len(self.reference_file.sectors):
                    self.finished = True


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
        self.log = open(self.reference_file.name + "_" + str(time.time()*1000) + ".log", 'w')
        #self.main(start_at)
        
    def main(self, start_at):        

        lock = Lock()
        #create required directories
        if not os.path.exists('tmp'):
            os.makedirs('tmp')
        if not os.path.exists('results'):
            os.makedirs('results')

        # start at position in bytes
        self.diskFd.seek(int(start_at, 16))

        # main loop
        while not self.finished:

            lock.acquire()
            start = time.perf_counter()
            data = self.diskFd.read(512)
            stop = time.perf_counter()
            self.perf.iteration(stop - start)

            Thread(name='checking sector @'+hex(self.diskFd.tell() - 512),target=self.check_sector,args=[data, hex(self.diskFd.tell() - 512)]).start()
            #self.check_sector(data, self.diskFd.tell(), self.success)
            lock.release()

            self.progressUpdate.emit([self.diskFd.tell(), self.perf.avg])

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
                result.append(bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])))   #trailing sector zfill
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
        file_info_grid.addWidget(QLabel(str(reference_file.size / 512) + " sectors"), 2, 1)        

        start_at_hbox = QHBoxLayout()
        start_at_label = QLabel("Start at address (search forward): ")
        self.start_at = QLineEdit()
        self.start_at.setText("0x6AAC73400")
        start_at_hbox.addWidget(start_at_label)
        start_at_hbox.addWidget(self.start_at)

        successes_hbox = QHBoxLayout()        
        self.successes = QLabel()
        self.successes.setText("0/0")
        successes_hbox.addWidget(self.successes)
        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(False)
        self.start = QPushButton('Start')
        self.progressPercentage = QLabel()
        self.sectorAverage = QLabel()
        
        self.reader = DiskReader(selected_vol, reference_file)
        
        self.start.clicked.connect(self.go)

        grid = QGridLayout()        
        grid.addLayout(file_info_grid, 0, 0)
        grid.addWidget(self.progressPercentage, 0, 2)
        grid.addWidget(self.sectorAverage, 1, 2)
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
        self.reader.progressUpdate.connect(self.updateProgress)
        self.reader.successUpdate.connect(self.updateSuccessCount)
     
        self.start.setText('...')
        self.start.setDisabled(True)
        self.start_at.setDisabled(True)  
        Thread(name='recreate main',target=self.reader.main,args=[self.start_at.text().split("x")[1]]).start()  

    def updateSuccessCount(self, i):
        successCount = 0 
        for entry in self.reader.rebuilt:
            if entry != None:
                successCount += 1
        
        self.successes.setText("sector " + str(i) + " rebuilt: " + str(successCount) + "/" + str(len(self.reader.rebuilt)))
        
    def updateProgress(self, progress):
        self.progressPercentage.setText("{:.7f}".format(100 * progress[0] / self.reader.diskSize.total) + "%")
        self.sectorAverage.setText("Average time per sector read: " + "{:.2f}".format(progress[1]) + " μs")
        self.progressBar.setValue(100 * progress[0] / self.reader.diskSize.total)     
