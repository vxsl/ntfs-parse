import time, os, zlib
from shutil import disk_usage
import config
from PerformanceCalc import PerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread

def parseAls(tmpFileName):
    print("trying to parse a .als file in ", tmpFileName, " ...")
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
        print("Decompression failed: " + str(e.args[0]))
        return 1

class DiskReader(QtCore.QObject):
    
    progressUpdate = QtCore.pyqtSignal(object)
    successUpdate = QtCore.pyqtSignal(object)
    def __init__(self):
        super().__init__()
        self.diskPath = r"\\." + "\\" + config.LOGICAL_VOLUME + ":"
        #diskPath = r"\\.\D:"
        disk = os.open(self.diskPath, os.O_RDONLY | os.O_BINARY)
        self.diskFd = os.fdopen(disk, 'rb')
        self.diskSize = disk_usage(config.LOGICAL_VOLUME + ':\\')
        self.perf = PerformanceCalc(self.diskFd)
        self.startAddr = -1
        self.successCount = [0, 0]


    def main(self):
        
        if not os.path.exists('tmp'):
            os.makedirs('tmp')
        if not os.path.exists('results'):
            os.makedirs('results')
        sectorCount = 0

        while True:
            start = time.perf_counter()
            data = self.diskFd.read(512)
            stop = time.perf_counter()
            self.perf.iteration(stop - start)

            if data.hex()[0:16] == "1f8b080000000000":
                if self.startAddr != -1:
                    f.close()
                    if parseAls(f.name) == 0:
                        self.successCount[0] += 1
                    else:
                        self.successCount[1] += 1
                    self.successUpdate.emit(self.successCount)
                f = open("tmp/block" + hex(self.diskFd.tell() - 512)+".tmp", "wb")    
                self.startAddr = self.diskFd.tell() - 512
                sectorCount = 0               

            if self.startAddr != -1:
                if sectorCount < 1000000000:
                    f.write(data)
                    sectorCount += 1
                else:
                    f.close()
                    os.remove(f.name)
                    sectorCount = 0
                    self.startAddr = -1
            self.progressUpdate.emit([self.diskFd.tell(), self.perf.avg])

            #print(data.hex())
            #print(hex(fileObj.tell()))

class mainWindow(QWidget):
    def __init__(self):
        super().__init__()       
        print("hereee")
        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(False)
        #progressBar.setGeometry(30,40,1000,25)
        self.start = QPushButton('Start')
        self.start.clicked.connect(self.startProgress)
        self.progressPercentage = QLabel()
        self.sectorAverage = QLabel()
        self.fails = QLabel()
        self.successes = QLabel()
        #progressPercentage.move(100, 15)

        layout = QGridLayout()
        #layout.addWidget(progressBar)
        layout.addWidget(self.progressPercentage, 0, 2)
        layout.addWidget(self.sectorAverage, 1, 2)
        layout.addWidget(self.fails, 2, 2)
        layout.addWidget(self.successes, 3, 2)        
        layout.addWidget(self.progressBar, 4, 0, 4, 3)        
        layout.addWidget(self.start, 9, 0)

        self.setLayout(layout)

        self.reader = DiskReader()
        self.reader.progressUpdate.connect(self.updateProgress)
        self.reader.successUpdate.connect(self.updateSuccessCount)

    def updateSuccessCount(self, successCount):
        self.fails.setText("Failures: " + str(successCount[1]))
        self.successes.setText("Successes: " + str(successCount[0]))

    def updateProgress(self, progress):
        self.progressPercentage.setText("{:.9f}".format(progress[0] / self.reader.diskSize.total) + "%")
        self.sectorAverage.setText("Average time per sector read: " + "{:.2f}".format(progress[1]) + " μs")
        self.progressBar.setValue(progress[0] / self.reader.diskSize.total)     

    def startProgress(self):        
        Thread(target=self.reader.main).start()
        self.start.setText('...')
        self.start.setDisabled(True)
    
    
app = QApplication([])

window = mainWindow()
window.setWindowTitle('ntfs-parse')
window.setGeometry(500, 500, 1000, 1000)

window.show()
app.exec_()

