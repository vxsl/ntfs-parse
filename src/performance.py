from time import perf_counter
from datetime import timedelta
from math import ceil
from PyQt5 import QtCore

SECTOR_SIZE = None
DEFAULT_SAMPLE_SIZE = 1000
express = True

class PerformanceCalculator():

    def __init__(self, volume_size, sector_size, **kwargs):

        global SECTOR_SIZE
        SECTOR_SIZE = sector_size

        try:
            self.sample_size = kwargs['sample_size']
        except KeyError:
            self.sample_size = DEFAULT_SAMPLE_SIZE

        try:
            self.avg = kwargs['init_avg']
        except KeyError:
            self.avg = 0

        try:
            self.jump_size = kwargs['jump_size']
            self.total_sectors_to_read = ceil(volume_size / self.jump_size)
            self.express = True
        except KeyError:
            self.jump_size = 1
            self.total_sectors_to_read = ceil(volume_size / SECTOR_SIZE)
            self.express = False

        self.children = []
        self.cur_start = None
        self.cur_incr = 0
        self.sectors_read = 0

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
            self.start()

    def get_remaining_seconds(self):
        result = (self.avg / (self.sample_size)) * \
                (self.total_sectors_to_read - self.sectors_read)
        return str(timedelta(seconds=result)).split(".")[0] + " remaining in skim"

    def get_remaining_estimate(self):
        if express:
            result = self.get_remaining_seconds()
            if result != 1:
                if not self.children:
                    return self.get_remaining_seconds()
                else:
                    children_seconds = max([c.get_remaining_seconds() for c in self.children])
                    if children_seconds > 0:
                        result = str(timedelta(seconds=children_seconds)).split(".")[0] \
                            + " until skim is resumed...\n" \
                            + self.get_remaining_seconds()
                    else:
                        result = 'Calculating delay before resuming skim...'
                    return result
            else:
                return "Calculating time remaining..."

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