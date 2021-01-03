from time import perf_counter
from datetime import timedelta
from math import ceil
from PyQt5 import QtCore

DEFAULT_SAMPLE_WINDOW = 5
DEFAULT_SAMPLE_SIZE = 1000
LARGER_SAMPLE_SIZE = 10000

class PerformanceCalculator(QtCore.QObject):

    new_average_signal = QtCore.pyqtSignal(tuple)

    def __init__(self, volume_size, jump_size, small_file, **kwargs):
        super().__init__()

        try:
            self.sample_size = kwargs['sample_size']
        except KeyError:
            if small_file:
                self.sample_size = LARGER_SAMPLE_SIZE
            else:
                self.sample_size = DEFAULT_SAMPLE_SIZE

        try:
            self.avg = kwargs['init_avg']
        except KeyError:
            self.avg = 0

        self.jump_size = jump_size
        self.total_sectors_to_read = ceil(volume_size / self.jump_size)

        self.children = []
        self.cur_start = None
        self.cur_incr = 0
        self.cur_sectors_read = 0
        self.total_sectors_read = 0
        self.next_reset = None

    @QtCore.pyqtSlot()
    def calculate_average(self):
        if self.avg > 0:
            self.avg += self.cur_sectors_read
            self.avg = (self.avg / 2)
        else:
            self.avg += self.cur_sectors_read
        self.new_average_signal.emit((self.avg, self.get_remaining_seconds()))
        self.cur_sectors_read = 0

    def start(self):
        return
        self.clock = QtCore.QTimer(self)
        #self.clock.timeout.connect(self.calculate_average)
        self.clock.timeout.connect(lambda: print('x'))
        self.clock.start(DEFAULT_SAMPLE_WINDOW * 1000)

    def increment(self):
        self.cur_sectors_read += 1
        self.total_sectors_read += 1
        return self.total_sectors_read / self.total_sectors_to_read
        """ if self.total_sectors_read >= self.next_reset:
            if self.avg > 0:
                self.avg += (perf_counter() - self.cur_start)
                self.avg = (self.avg / 2)
            else:
                self.avg += (perf_counter() - self.cur_start)
            self.new_average_signal.emit((self.avg, self.get_remaining_seconds()))
            self.start()
        return self.total_sectors_read / self.total_sectors_to_read """

    def get_remaining_seconds(self):
        """ return (self.avg / (self.sample_size)) * \
                (self.total_sectors_to_read - self.total_sectors_read) """
        try:
            return self.total_sectors_to_read / self.avg / DEFAULT_SAMPLE_WINDOW
        except:
            return 0

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