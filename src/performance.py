from time import perf_counter
from datetime import timedelta
from math import ceil
from PyQt5 import QtCore

SAMPLE_WINDOW = 5

class PerformanceCalculator(QtCore.QObject):

    new_average_signal = QtCore.pyqtSignal(tuple)

    def __init__(self, volume_size, jump_size, jump_sectors, **kwargs):
        super().__init__()
        try:
            self.avg = kwargs['init_avg']
        except KeyError:
            self.avg = 0
        self.jump_sectors = jump_sectors
        self.total_sectors_to_read = ceil(volume_size / jump_size)
        self.cur_sectors_read = 0
        self.total_sectors_read = 0

    def calculate_average(self):
        if self.avg > 0:
            self.avg += self.cur_sectors_read
            self.avg = (self.avg / 2)
        else:
            self.avg += self.cur_sectors_read
        self.new_average_signal.emit((self.avg, self.get_remaining_seconds()))
        self.cur_sectors_read = 0
    
    def get_remaining_seconds(self):
        try:
            return SAMPLE_WINDOW * self.total_sectors_to_read / self.avg
        except ZeroDivisionError:
            return 0

    def increment(self):
        self.cur_sectors_read += 1
        self.total_sectors_read += 1
        return self.total_sectors_read / self.total_sectors_to_read


class InspectionPerformanceCalc(QtCore.QObject):

    new_average_signal = QtCore.pyqtSignal(tuple)

    def __init__(self, total_sectors, id_str):
        super().__init__()
        self.id_str = id_str
        self.avg = 0
        self.cur_start = None
        self.sectors_read = 0
        self.sample_size = 1000
        self.total_sectors_to_read = total_sectors
        self.next_reset = None

    def start(self):
        self.next_reset = self.sectors_read + self.sample_size
        self.cur_start = perf_counter()

    def increment(self):
        self.sectors_read += 1
        if self.sectors_read >= self.next_reset:
            if self.avg > 0:
                self.avg += (perf_counter() - self.cur_start)
                self.avg = (self.avg / 2)
            else:
                self.avg += (perf_counter() - self.cur_start)
            self.new_average_signal.emit((self.avg, self.id_str))
            self.start()

    def get_remaining_seconds(self):
        return (self.avg / self.sample_size) * (self.total_sectors_to_read - self.sectors_read)

    def get_remaining_estimate(self):
        seconds = self.get_remaining_seconds()
        if seconds > 0:
            #return str(timedelta(seconds=self.get_remaining_seconds())).split(".")[0] + " remaining"
            return timedelta(seconds=self.get_remaining_seconds()).seconds
        else:
            return '...'