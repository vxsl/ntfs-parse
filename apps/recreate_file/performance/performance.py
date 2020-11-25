from time import perf_counter

class PerformanceCalc:
    def __init__(self):
        self.sample_size = 100000
        self.avg = 0
        self.cur_incr = 0
        self.cur_start = None

    def start(self):
        self.cur_incr = 0
        self.cur_start = perf_counter()

    def increment(self):
        self.cur_incr += 1
        if self.cur_incr >= self.sample_size:
            cur_stop = perf_counter()
            self.avg += (cur_stop - self.cur_start)
            self.avg = (self.avg / 2)
            self.start()

class ExpressPerformanceCalc(PerformanceCalc):
    def __init__(self, skip_size):
        super().__init__()
        self.skip_size = skip_size
        self.sample_size = 1000000
        self.increment_mark = self.sample_size/self.skip_size

    def increment(self):
        self.cur_incr += 1
        if self.cur_incr >= self.increment_mark:
            self.avg += (perf_counter() - self.cur_start)
            self.avg = (self.avg / 2)
            self.start()
            