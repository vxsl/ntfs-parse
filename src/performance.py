from math import ceil
from PyQt5 import QtCore

SAMPLE_WINDOW = 5

class PerformanceCalculator(QtCore.QObject):

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
        self.cur_sectors_read = 0
        return (self.avg, self.get_remaining_seconds())

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

    def __init__(self, total_sectors, id_str):
        super().__init__()
        self.id_str = id_str
        self.avg = 0
        self.sample_size = 1000
        self.cur_sectors_read = 0
        self.total_sectors_read = 0
        self.total_sectors_to_read = total_sectors

    def calculate_average(self):
        if self.avg > 0:
            self.avg += self.cur_sectors_read
            self.avg = (self.avg / 2)
        else:
            self.avg += self.cur_sectors_read
        self.cur_sectors_read = 0
        return self.avg

    def increment(self):
        self.cur_sectors_read += 1
        self.total_sectors_read += 1
        return self.total_sectors_read / self.total_sectors_to_read

    def get_remaining_seconds(self):
        try:
            return SAMPLE_WINDOW * self.total_sectors_to_read / self.avg
        except ZeroDivisionError:
            return 0
