import time, os

class PerformanceCalc:
    def __init__(self, fileObj):
        self.iter = []
        self.cur_sum = 0
        self.cur_count = 0 
        print("Initial read speed test...")
        for i in range(0, 100000):  # TODO change this to be dynamic in case the disk is small..?
            start = time.perf_counter()
            fileObj.read(512)  
            stop = time.perf_counter()
            self.iter.append(stop - start)
        self.avg = (1000000 * sum(self.iter) / len(self.iter))
        del self.iter[:]
        print("Initial read speed test finished.")
        fileObj.seek(0)

    def iteration(self, duration):
        self.cur_sum += duration
        self.cur_count += 1
        if self.cur_count == 1000000:
            cur_avg = 1000000 * self.cur_sum / self.cur_count        
            #print("avg = " +  f"{self.avg:.3f}" + " + " + f"{cur_avg:.3f}")            
            self.avg += cur_avg  
            self.avg = self.avg / 2  
            self.cur_sum = 0
            self.cur_count = 0
            #print("avg = " +  f"{self.avg:.3f}" + " μs")