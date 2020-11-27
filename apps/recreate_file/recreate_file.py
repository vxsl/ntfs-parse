import time, os, copy
from shutil import disk_usage
from threading import Thread, Lock, current_thread
from concurrent import futures
from multiprocessing import cpu_count
from PyQt5 import QtCore
from .performance.performance import PerformanceCalc, ExpressPerformanceCalc

SECTOR_SIZE = 512 # bytes
EMPTY_SECTOR = b'\x00' * SECTOR_SIZE
lock = Lock()
job = None
executor = futures.ThreadPoolExecutor(max_workers=(cpu_count()))

def check_sector(inp, addr, already_in_close_inspection=False):
    for og_sector_index, sector in job.source_file.remaining_sectors:
        if inp == sector and (addr, sector) not in job.rebuilt_file:
            hex_addr = hex(addr - SECTOR_SIZE)
            with lock:
                job.rebuilt_file[og_sector_index] = (addr, copy.deepcopy(sector))
                job.source_file.remaining_sectors.remove((og_sector_index, sector))
            job.success_update.emit(og_sector_index)
            if not already_in_close_inspection and not job.primary_reader.inspection_in_progress(addr):
                close_inspect(addr)
            print("check_sector: sector at logical address " + hex_addr + " on disk is equal to sector " + str(og_sector_index) + " of source file.")            
            job.log.write(hex_addr + "\t\t" + str(og_sector_index) + "\n")
            job.log.flush()
            return
    return

def close_inspect(addr):
    forward = ForwardCloseReader()
    backward = BackwardCloseReader()
    job.primary_reader.inspections.append((hex(addr), forward))
    job.primary_reader.inspections.append((hex(addr), backward))
    #Thread(name='close inspect forward @' + addr,target=forward.read,args=[addr]).start()
    #Thread(name='close inspect backward @' + addr,target=backward.read,args=[addr]).start()
    executor.submit(forward.read, addr)
    executor.submit(backward.read, addr)


class DiskReader(QtCore.QObject):
    def __init__(self, disk_path):
        super().__init__()
        self.fd = os.fdopen(os.open(disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):
    def __init__(self):
        super().__init__(job.disk_path)
        self.sector_limit = (job.total_sectors * 6) #???
        self.sector_count = 0

class ForwardCloseReader(CloseReader):
    def read(self, addr):
        current_thread().name = ("Forward close reader at " + hex(addr))
        self.fd.seek(addr)
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(SECTOR_SIZE), self.fd.tell(), True)
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        return

class BackwardCloseReader(CloseReader):
    def read(self, addr):
        current_thread().name = ("Backward close reader at " + hex(addr))
        self.fd.seek(addr)
        for _ in range(self.sector_limit):
            check_sector(self.fd.read(SECTOR_SIZE), self.fd.tell(), True)
            self.fd.seek(-1024, 1)
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        return

class PrimaryReader(DiskReader):

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(SECTOR_SIZE), self.fd.tell())
            executor.submit(job.perf.increment())


class ExpressPrimaryReader(PrimaryReader):

    def __init__(self, disk_path, total_sectors):
        super().__init__(disk_path)
        self.jump_size = total_sectors//2 * SECTOR_SIZE
        self.inspections = []

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))

        for _ in range(job.diskSize.total - addr):
            data = self.fd.read(SECTOR_SIZE)
            if not data:
                break
            if data != EMPTY_SECTOR:
                executor.submit(check_sector, self.fd.read(SECTOR_SIZE), self.fd.tell())
            else:
                print("EMPTY SECTOR")
            executor.submit(job.perf.increment)
            self.fd.seek(self.jump_size, 1)

        job.finished.emit(None)

    def inspection_in_progress(self, addr):
        for address, reader in self.inspections:
            upper_limit = int(address, 16) + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = int(address, 16) - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False

class Job(QtCore.QObject):

    # PyQt event signaller
    success_update = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal(object)

    def __init__(self, vol, source_file, do_logging, express):
        super().__init__()
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.diskSize = disk_usage(vol + ':\\')
        self.source_file = source_file
        self.done_sectors = 0
        self.total_sectors = len(source_file.sectors)
        self.rebuilt_file = [None] * self.total_sectors

        if express == True:
            self.primary_reader = ExpressPrimaryReader(self.disk_path, self.total_sectors)
            self.perf = ExpressPerformanceCalc(self.total_sectors)
        else:
            job.primary_reader = PrimaryReader(self.disk_path)
            job.perf = PerformanceCalc()

        if do_logging == True:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.source_file.name + ".log", 'w')
        else:
            dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(dir_name, mode=0o755)
            self.log = open(dir_name + '/' + self.source_file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")

class SourceFile():
    def __init__(self, path):
        self.sectors = self.to_sectors(path)
        self.remaining_sectors = []
        for i in range(len(self.sectors)):
            self.remaining_sectors.append((i, copy.deepcopy(self.sectors[i])))
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def to_sectors(self, path):
        file = open(path, "rb")
        file.seek(0)
        result = []
        while True:
            cur = file.read(SECTOR_SIZE)
            if cur == b'':
                break
            elif len(cur) == SECTOR_SIZE:
                result.append(cur)
            else:
                result.append((bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])), False))   #trailing sector zfill
        return result

def initialize_job(do_logging, express, selected_vol, source_file):
    global job
    job = Job(selected_vol, source_file, do_logging, express)
    return job

