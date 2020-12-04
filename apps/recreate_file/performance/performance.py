from time import perf_counter
from datetime import timedelta
from math import ceil

SECTOR_SIZE = None
SAMPLE_SIZE = 1000

class ExpressPerformanceCalc():
    
    def __init__(self, skip_size, disk_size, sector_size, init_avg=0):
        
        global SECTOR_SIZE
        SECTOR_SIZE = sector_size

        self.children = []
        self.avg = init_avg
        self.cur_start = None
        self.cur_incr = 0
        self.skip_size = skip_size
        self.sectors_read = 0        
        self.sample_size = SAMPLE_SIZE
        self.total_sectors_to_read = ceil(disk_size / skip_size)

    def start(self):
        self.next_reset = self.sectors_read + self.sample_size
        #self.cur_incr = 0
        self.cur_start = perf_counter()

    def increment(self):
        self.sectors_read += 1
        #self.cur_incr += 1
        #print(self.sectors_read)
        if self.sectors_read >= self.next_reset:
        #if self.cur_incr >= self.sample_size:
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
        #seconds = self.avg * ((self.total - self.sectors_read) / (SECTOR_SIZE * self.sample_size))
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

class InspectionPerformanceCalc():

    def __init__(self, total_sectors):
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
            self.start()

    def get_remaining_seconds(self):
        return (self.avg / self.sample_size) * (self.total_sectors_to_read - self.sectors_read)

    def get_remaining_estimate(self):
        seconds = self.get_remaining_seconds()
        if seconds > 0:
            return str(timedelta(seconds=self.get_remaining_seconds())).split(".")[0] + " remaining"
        else:
            return '...'