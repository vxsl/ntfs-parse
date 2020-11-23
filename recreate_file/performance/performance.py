import time

SAMPLE_SIZE = 100000

class PerformanceCalc:
    def __init__(self, fileObj):
        self.sample_size = SAMPLE_SIZE
        self.avg = 0

        """ print("Initial read speed test...")
        self.start()
        while self.cur_incr < 1000:
            tmp = fileObj.read(512)
            print(tmp)
            self.cur_incr += 1
        cur_stop = time.perf_counter()
        self.avg += (cur_stop - self.cur_start) * (self.sample_size / 1000)
        print("Initial read speed test finished, initial average = " + "{:.2f}".format(self.avg))            """   


    def start(self):
        self.cur_incr = 0
        self.cur_start = time.perf_counter()

    def increment(self):
        self.cur_incr += 1
        if self.cur_incr >= self.sample_size:
            cur_stop = time.perf_counter()
            self.avg += (cur_stop - self.cur_start) 
            self.avg = (self.avg / 2)
            self.start()

    """ def iteration(self, duration):
        self.cur_sum += duration
        self.cur_count += 1
        if self.cur_count >= SECTOR_COUNT:
            #print("avg = " +  f"{self.avg:.3f}" + " + " + f"{cur_avg:.3f}")            
            self.avg += self.cur_sum  
            self.avg = self.avg / 2  
            self.cur_sum = 0
            self.cur_count = 0
            #print("avg = " +  f"{self.avg:.3f}" + " μs") """