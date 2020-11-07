import time, os

class PerformanceCalc:
    def __init__(self, disk, fileObj):
        self.iter = []
        for i in range(0, 100000):  # TODO change this to be dynamic in case the disk is small..?
            start = time.perf_counter()
            data = os.read(disk, 512)
            stop = time.perf_counter()
            self.iter.append(stop - start)
        self.avg = (1000000 * sum(self.iter) / len(self.iter))
        del self.iter[:]
        fileObj.seek(0)

    def iteration(self, duration):
        self.iter.append(duration)
        if len(self.iter) == 1000000:        
            curAvg = (1000000 * sum(self.iter) / len(self.iter))
            print("avg = " +  f"{self.avg:.3f}" + " + " + f"{curAvg:.3f}")
            
            self.avg += curAvg  
            self.avg = self.avg / 2  

            print("avg = " +  f"{self.avg:.3f}" + " μs")
            del self.iter[:]