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
            return
        else:            
            if split[2][0:7] != b"Ableton":
                #print("not a .als file")
                os.remove(tmpFileName)
                return
            else:                
                als = open(tmpFileName.split(".")[0]+".als", "wb")    
                als.write(unzipped)
                als.close()
                tmpFile.close()            
                os.remove(tmpFileName)
                print("Success: " + als.name)
    
    except Exception as e:
        tmpFile.close()            
        os.remove(tmpFileName)
        print("Decompression failed: " + e.args[0])
        return

class DiskReader(QtCore.QObject):
    
    progressUpdate = QtCore.pyqtSignal(float)
    def __init__(self):
        super().__init__()
        self.diskPath = r"\\." + "\\" + config.LOGICAL_VOLUME + ":"
        #diskPath = r"\\.\D:"
        disk = os.open(self.diskPath, os.O_RDONLY | os.O_BINARY)
        self.diskFd = os.fdopen(disk, 'rb')
        self.diskSize = disk_usage(config.LOGICAL_VOLUME + ':\\')
        self.perf = PerformanceCalc(self.diskFd)
        self.startAddr = -1


    def main(self):
        sectorCount = 0

        while True:
            start = time.perf_counter()
            data = self.diskFd.read(512)
            stop = time.perf_counter()
            self.perf.iteration(stop - start)

            if data.hex()[0:16] == "1f8b080000000000":
                if self.startAddr != -1:
                    f.close()
                    parseAls(f.name)
                f = open("block" + hex(self.diskFd.tell() - 512)+".tmp", "wb")    
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
            self.progressUpdate.emit(self.diskFd.tell())

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
        self.msg = QLabel('test')
        #msg.move(100, 15)

        layout = QGridLayout()
        #layout.addWidget(progressBar)
        layout.addWidget(self.start, 2, 0)
        layout.addWidget(self.progressBar, 1, 0, 1, 3)
        layout.addWidget(self.msg, 0, 2)

        self.setLayout(layout)

        self.reader = DiskReader()
        self.reader.progressUpdate.connect(self.updateProgress)

    def updateProgress(self, progress):
        self.msg.setText("{:.5f}".format(progress / self.reader.diskSize.total) + "%")
        self.progressBar.setValue(progress / self.reader.diskSize.total)     

    def startProgress(self):        
        Thread(target=self.reader.main).start()
    
    
app = QApplication([])

window = mainWindow()
window.setWindowTitle('ntfs-parse')
window.setGeometry(500, 500, 1000, 1000)

window.show()
app.exec_()

