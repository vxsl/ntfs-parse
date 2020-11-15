import time, os, zlib, string
from shutil import disk_usage
from PerformanceCalc import PerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread

# returns 0 for success, 1 otherwise
def readGzip(tmpFileName):
    print("trying to read a .gzip archive in ", tmpFileName, " ...")
    tmpFile = open(tmpFileName, "rb")

    try:
        unzipper = zlib.decompressobj(32 + zlib.MAX_WBITS)
        unzipped = unzipper.decompress(tmpFile.read())   
        split = unzipped.split(b'<')
        if split[1][0:4] != b'?xml':
            #print("not an XML file")
            tmpFile.close()
            os.remove(tmpFileName)
            return 1
        else:            
            if split[2][0:7] != b"Ableton":
                #print("not a .als file")
                os.remove(tmpFileName)
                return 1
            else:                
                als = open("results/" + tmpFileName.split("/")[1].split(".")[0] +".als", "wb")    
                als.write(unzipped)
                als.close()
                tmpFile.close()            
                os.remove(tmpFileName)
                print("Success: " + als.name)
                return 0
    
    except Exception as e:
        tmpFile.close()            
        os.remove(tmpFileName)
        #print("Decompression failed: " + str(e.args[0]))
        return 1

class DiskReader(QtCore.QObject):
    
    # PyQt event signallers
    progressUpdate = QtCore.pyqtSignal(object)
    successUpdate = QtCore.pyqtSignal(object)

    def __init__(self, vol):
        super().__init__()
        self.diskPath = r"\\." + "\\" + vol + ":"
        disk = os.open(self.diskPath, os.O_RDONLY | os.O_BINARY)
        self.diskFd = os.fdopen(disk, 'rb')
        self.diskSize = disk_usage(vol + ':\\')
        self.perf = PerformanceCalc(self.diskFd)
        self.successCount = [0, 0]

    def main(self):        

        #create required directories
        if not os.path.exists('tmp'):
            os.makedirs('tmp')
        if not os.path.exists('results'):
            os.makedirs('results')

        # TODO instead of capping it like this, just remove current gb from RAM and keep going? How do we determine whether to keep going...? Hmm...
        currentSequentialSectors = 0    # no potential file should be larger than, let's say, 1 GB. This variable will keep track of this to prevent the program from endlessly searching, or se for the next occurrence of the .gzip start marker. 
        currentGzipStart = -1

        # start at position in bytes
        self.diskFd.seek(int('1bdff6f9000', 16))

        # main loop
        while True:
            start = time.perf_counter()
            data = self.diskFd.read(512)
            stop = time.perf_counter()
            self.perf.iteration(stop - start)

            # TODO is there a sensible way of multithreading the parsing?
            if data.hex()[0:16] == "1f8b080000000000":
                if currentGzipStart != -1:
                    f.close()
                    if readGzip(f.name) == 0:
                        self.successCount[0] += 1
                    else:
                        self.successCount[1] += 1
                    self.successUpdate.emit(self.successCount)
                f = open("tmp/block" + hex(self.diskFd.tell() - 512)+".tmp", "wb")    
                currentGzipStart = self.diskFd.tell() - 512
                currentSequentialSectors = 0               

            if currentGzipStart != -1:
                if currentSequentialSectors < 1000000000:
                    f.write(data)
                    currentSequentialSectors += 1
                else:
                    f.close()
                    os.remove(f.name)
                    currentSequentialSectors = 0
                    currentGzipStart = -1
            self.progressUpdate.emit([self.diskFd.tell(), self.perf.avg])



class MainWindow(QWidget):
    def __init__(self, selected_vol):
        super().__init__()      

        """ dlg = StartDialog()
        dlg.exec()

        selected_vol = dlg.vol_select_dropdown.currentText()[0]
        print("selected " + selected_vol) """

        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(False)
        self.start = QPushButton('Start')
        self.start.clicked.connect(self.startProgress)
        self.progressPercentage = QLabel()
        self.sectorAverage = QLabel()
        self.fails = QLabel()
        self.successes = QLabel()

        layout = QGridLayout()
        layout.addWidget(self.progressPercentage, 0, 2)
        layout.addWidget(self.sectorAverage, 1, 2)
        layout.addWidget(self.fails, 2, 2)
        layout.addWidget(self.successes, 3, 2)        
        layout.addWidget(self.progressBar, 4, 0, 4, 3)        
        layout.addWidget(self.start, 9, 0)

        self.setLayout(layout)

        self.reader = DiskReader(selected_vol)
        self.reader.progressUpdate.connect(self.updateProgress)
        self.reader.successUpdate.connect(self.updateSuccessCount)
        

    def updateSuccessCount(self, successCount):
        self.fails.setText("Failures: " + str(successCount[1]))
        self.successes.setText("Successes: " + str(successCount[0]))

    def updateProgress(self, progress):
        self.progressPercentage.setText("{:.7f}".format(100 * progress[0] / self.reader.diskSize.total) + "%")
        self.sectorAverage.setText("Average time per sector read: " + "{:.2f}".format(progress[1]) + " μs")
        self.progressBar.setValue(100 * progress[0] / self.reader.diskSize.total)     

    def startProgress(self):        
        Thread(target=self.reader.main).start()
        self.start.setText('...')
        self.start.setDisabled(True)
    