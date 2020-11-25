from PyQt5 import QtCore
import time, os, copy
from shutil import disk_usage
from threading import Thread, Lock
from concurrent import futures
from multiprocessing import cpu_count
from .performance.performance import PerformanceCalc, ExpressPerformanceCalc
#import cProfile, pstats, io ##

lock = Lock()

def check_sector(inp, addr, already_in_close_inspection=False):
    for sector in job.reference_file.remaining_sectors:
        if inp == sector and (addr, sector) not in job.rebuilt_file:
            addr = hex(addr - 512)
            with lock:
                i = job.reference_file.sectors.index(sector)
                job.rebuilt_file[i] = (addr, copy.deepcopy(sector))       
                job.reference_file.remaining_sectors.pop(job.reference_file.remaining_sectors.index(sector))            
            job.success_update.emit(i)
            job.log.write(str(addr) + "\t\t" + str(i) + "\n")
            job.log.flush()
            print("check_sector: sector at logical address " + addr + " on disk is equal to sector " + str(i) + " of reference file.")            
            if not already_in_close_inspection:
                close_inspect(addr)
            return
    return

def close_inspect(addr):
    fwd = ForwardCloseReader()
    bkwd = BackwardCloseReader()
    job.readers.append(fwd)
    job.readers.append(bkwd)
    Thread(name='close inspect forward @' + addr,target=fwd.read,args=[addr]).start()
    Thread(name='close inspect backward @' + addr,target=bkwd.read,args=[addr]).start()

class DiskReader(QtCore.QObject):
    
    def __init__(self):
        super().__init__()
        self.fd = os.fdopen(os.open(job.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):
    def __init__(self):
        super().__init__()
        self.sector_limit = (job.total_sectors * 6) #??? 

class ForwardCloseReader(CloseReader):
    def __init__(self):
        super().__init__()

    def read(self, addr):
        self.sector_count = 0
        self.fd.seek(int(addr, 16))
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(512), self.fd.tell(), True)

class BackwardCloseReader(CloseReader):
    def __init__(self):
        super().__init__()
    def read(self, addr):
        self.sector_count = 0
        self.fd.seek(int(addr, 16))
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(512), self.fd.tell(), True)
            self.fd.seek(-1024, 1)


class PrimaryReader(DiskReader):

    progress_update = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()

    def read(self, addr):
        """ pr = cProfile.Profile()
        pr.enable()  # start profiling """

        self.fd.seek(int(addr, 16))
        executor = futures.ThreadPoolExecutor(thread_name_prefix="Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(512), self.fd.tell())
            self.progress_update.emit(self.fd.tell())
            job.perf.increment()

        """ pr.disable()  # end profiling
        sortby = 'cumulative'
        ps = pstats.Stats(pr, stream=io.StringIO).sort_stats(sortby)
        ps.print_stats() """
            

class ExpressPrimaryReader(PrimaryReader):

    progress_update = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.jump_size = job.total_sectors//2 * 512
        
    def read(self, addr):
        self.fd.seek(int(addr, 16))
        executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(512), self.fd.tell())
            executor.submit(job.perf.increment)
            self.fd.seek(self.jump_size, 1) # TODO 512 = ALLOCATION_UNIT
            
class Job(QtCore.QObject):    

    # PyQt event signallers
    success_update = QtCore.pyqtSignal(object)
    
    def __init__(self, vol, reference_file, do_logging, express):
        super().__init__()
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"   
        self.diskSize = disk_usage(vol + ':\\')
        self.reference_file = reference_file
        self.finished = False
        self.done_sectors = 0
        self.total_sectors = len(reference_file.sectors)         
        self.rebuilt_file = [None] * self.total_sectors
        self.readers = []
        #self.readers.append(DiskReader(self.disk_path))
        
        if do_logging == True:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.reference_file.name + ".log", 'w')
        else:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.reference_file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")


class ReferenceFile():
    def __init__(self, path):
        split = path.split('/')
        self.fd = open(path, "rb")
        self.sectors = self.to_sectors(self.fd)
        self.remaining_sectors = copy.deepcopy(self.sectors)
        self.size = os.stat(path).st_size
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def to_sectors(self, file):
        file.seek(0)
        result = []
        while True:
            cur = file.read(512)
            if cur == b'':
                break
            elif len(cur) == 512:
                result.append(cur)
            else:
                result.append((bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])), False))   #trailing sector zfill
        return result

def initialize_job(do_logging, express, selected_vol, reference_file):
    global job
    if express == True:
        job = Job(selected_vol, reference_file, do_logging, True)
        job.primary_reader = ExpressPrimaryReader()
        job.perf = ExpressPerformanceCalc(job.total_sectors)
    else:
        job = Job(selected_vol, reference_file, do_logging, False)
        job.primary_reader = PrimaryReader()            
        job.perf = PerformanceCalc()
    return job

