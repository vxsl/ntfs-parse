import time, os, copy
from shutil import disk_usage
from threading import Thread, Lock, current_thread
from PyQt5 import QtCore
from .performance.performance import PerformanceCalc, ExpressPerformanceCalc
import sys

SECTOR_SIZE = 512 # bytes
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]
lock = Lock()
job = None
executor = None

#addr == int('4191FFA5000', 16) and inp == sector
def check_sector(inp, addr, close_reader=None):
    for sector in filter(None, job.source_file.remaining_sectors):
        if inp == sector and ((addr - SECTOR_SIZE), sector) not in job.rebuilt_file:
            hex_addr = hex(addr - SECTOR_SIZE)
            with lock:
                i = job.source_file.get_unique_sector_index(sector)
                job.rebuilt_file[i] = ((addr - SECTOR_SIZE), copy.deepcopy(sector))
                job.source_file.remaining_sectors.remove(sector)
            job.success_signal.emit(i)
            if close_reader:
                close_reader.success_count += 1
            elif not job.primary_reader.inspection_in_progress(addr):
                job.begin_close_inspection(addr - SECTOR_SIZE)
            #print(str(close_reader) + ": sector at logical address " + hex_addr + " on disk is equal to sector " + str(i) + " of source file.")            
            job.log.write(hex_addr + "\t\t" + str(i) + "\n")
            job.log.flush()
            if not job.finished and not list(filter(None, job.source_file.remaining_sectors)):
                job.finish()
            return
    return


class DiskReader(QtCore.QObject):
    def __init__(self, disk_path):
        super().__init__()
        self.fd = os.fdopen(os.open(disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):
    def __init__(self):
        super().__init__(job.disk_path)
        self.sector_limit = (job.total_sectors * 2) #???
        self.sector_count = 0
        self.success_count = 0
        # TODO increase perf total because we have just added self.sector_limit sectors to check....

    def read(self, addr):
        current_thread().name = ("Backward close reader at " + hex(addr))
        self.fd.seek(addr)
        for _ in range(self.sector_limit):
            data = self.fd.read(SECTOR_SIZE)
            if job.finished or not data:
                break
            if data not in MEANINGLESS_SECTORS or self.success_count > (self.sector_count / 2):
                executor.submit(check_sector, data, self.fd.tell(), self)
            self.sector_count += 1
            # TODO increment perf
        return

class ForwardCloseReader(CloseReader):
    def read(self, addr):
        super().read(addr)
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a forward inspection at " + hex(addr))
        return


class BackwardCloseReader(CloseReader):
    def read(self, addr):
        super().read(addr - (self.sector_limit * SECTOR_SIZE))
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a backward inspection at " + hex(addr))
        return

class ExpressPrimaryReader(DiskReader):

    def __init__(self, disk_path, total_sectors):
        super().__init__(disk_path)
        self.jump_size = total_sectors//2 * SECTOR_SIZE
        self.inspections = []

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))
        while self.inspections:
            print('Waiting for close inspections to complete before resuming express search at address ' + hex(self.fd.tell()))
            time.sleep(3)
        for _ in range(job.diskSize.total - addr):
            data = self.fd.read(SECTOR_SIZE)
            if job.finished or not data or self.inspections:
                break
            if data not in MEANINGLESS_SECTORS:
                executor.submit(check_sector, data, self.fd.tell())
            executor.submit(job.perf.increment)
            self.fd.seek(self.jump_size, 1)

        if self.inspections and not job.finished:
            self.read(self.fd.tell())
        #job.finished_signal.emit(False)

    def inspection_in_progress(self, addr):
        for address, reader in self.inspections:
            upper_limit = int(address, 16) + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = int(address, 16) - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False
    
class Job(QtCore.QObject):

    # PyQt event signaller
    success_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(bool)
    new_inspection_signal = QtCore.pyqtSignal(object)

    def update_log(self):
        for i in range(len(self.rebuilt_file)):
            self.log.write("Sector " + i + ":\t\t" + self.rebuilt_file[i][0])

    def begin_close_inspection(self, addr):
        inspection = self.close_inspection(addr)
        self.new_inspection_signal.emit(inspection)

    class close_inspection:
        def __init__(self, addr):
            self.addr = addr
            self.forward = ForwardCloseReader()
            self.backward = BackwardCloseReader()
            job.primary_reader.inspections.append((hex(self.addr), self.forward))
            job.primary_reader.inspections.append((hex(self.addr), self.backward))
            #Thread(name='close inspect forward @' + self.addr,target=forward.read,args=[self.addr]).start()
            #Thread(name='close inspect backward @' + self.addr,target=backward.read,args=[self.addr]).start()
            executor.submit(self.forward.read, self.addr)
            executor.submit(self.backward.read, self.addr)
            
    def finish(self):
        self.finished = True
        out_file = open(self.rebuilt_file_path, 'wb')
        for addr, sector in self.rebuilt_file:
            out_file.write(sector)
        out_file.close()
        self.finished_signal.emit(True)

    def __init__(self, vol, source_file, do_logging, express):
        super().__init__()
        self.finished = False
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.diskSize = disk_usage(vol + ':\\')
        self.source_file = source_file
        self.done_sectors = 0
        self.total_sectors = len(source_file.sectors)
        self.rebuilt_file = [None] * self.total_sectors
        #self.finished_signal.connect(self.build_file)

        if express == True:
            self.primary_reader = ExpressPrimaryReader(self.disk_path, self.total_sectors)
            self.perf = ExpressPerformanceCalc(self.total_sectors)
        else:
            self.primary_reader = PrimaryReader(self.disk_path)
            self.perf = PerformanceCalc()

        if do_logging == True:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.source_file.name + ".log", 'w')
        else:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.source_file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")

        self.rebuilt_file_path = self.dir_name + '/' + self.source_file.name.split('.')[0] + "_RECONSTRUCTED." + self.source_file.name.split('.')[1]




class SourceFile():
    def __init__(self, path):
        self.sectors = self.to_sectors(path)
        self.remaining_sectors = copy.deepcopy(self.sectors)
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def get_unique_sector_index(self, sector):

        occurrences = [i for i, s in enumerate(self.sectors) if s == sector] # get all occurences of this data
        if len(occurrences) > 1:
            for index in occurrences:
                if job.rebuilt_file[index] == None:
                    return index
        else:
            return occurrences[0]


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
                result.append(bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])))   #trailing sector zfill
        return result

def initialize_job(do_logging, express, selected_vol, source_file, ex):
    global executor
    executor = ex
    global job
    job = Job(selected_vol, source_file, do_logging, express)
    return job

