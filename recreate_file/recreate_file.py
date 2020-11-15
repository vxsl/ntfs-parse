import time, os, zlib, string
from shutil import disk_usage
from PerformanceCalc import PerformanceCalc
from PyQt5 import QtCore
from PyQt5 import *
from PyQt5.QtWidgets import *
from threading import Thread

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
