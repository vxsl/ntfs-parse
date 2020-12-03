import time, os, copy
from shutil import disk_usage
from threading import Thread, Lock, current_thread
from PyQt5 import QtCore
from .performance.performance import ExpressPerformanceCalc, InspectionPerformanceCalc
import sys

SECTOR_SIZE = 512 # bytes
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]
lock = Lock()
job = None
executor = None

#addr == int('4191FFA5000', 16) and inp == sector
""" def check_sector(inp, addr, close_reader=None):
    for sector in filter(None, job.file.remaining_sectors):
        #if inp == sector and ((addr - SECTOR_SIZE), sector) not in job.rebuilt_file:
        if inp == sector:
            hex_addr = hex(addr - SECTOR_SIZE)
            with lock:
                i = job.file.get_unique_sector_index(sector)
                job.rebuilt_file[i] = ((addr - SECTOR_SIZE), copy.deepcopy(sector))
                job.file.remaining_sectors.remove(sector)
            job.success_signal.emit(i)
            if close_reader:
                close_reader.success_count += 1
            elif not job.primary_reader.inspection_in_progress(addr):
                job.begin_close_inspection(addr - SECTOR_SIZE)
            #print(str(close_reader) + ": sector at logical address " + hex_addr + " on disk is equal to sector " + str(i) + " of source file.")
            job.log.write(hex_addr + "\t\t" + str(i) + "\n")
            job.log.flush()
            if not job.finished and not list(filter(None, job.file.remaining_sectors)):
                job.finish()
            return
    return """

""" def check_sector(inp, addr, close_reader=None):
    #if inp == any(filter(None, job.file.remaining_sectors)):
    indexes = [index for index, entry in enumerate(job.file.sectors) if entry[0] == inp]
    if indexes:
    #if inp in [entry[0] for entry in job.file.sectors]:
        actual_address = addr - SECTOR_SIZE
        with lock:
            #indexes = [index for index, entry in enumerate(job.file.sectors) if entry[0] == inp]
            for i in indexes:
                job.file.sectors[i][1].append(actual_address)
        job.success_signal.emit(indexes)
        if close_reader:
            close_reader.success_count += 1
        elif not job.primary_reader.inspection_in_progress(addr):
            job.begin_close_inspection(actual_address)
        if not job.finished and not [index for index, entry in enumerate(job.file.sectors) if not entry[1]]:
            job.finish()
        return
    return """

def check_sector(inp, addr, close_reader=None):
    #if inp == any(filter(None, job.file.remaining_sectors)):
    #indexes = [index for index, entry in enumerate(job.file.sectors) if entry[0] == inp]
    indexes = [i for i, sector in enumerate(job.file.remaining_sectors) if sector == inp]
    if indexes:
    #if inp in [entry[0] for entry in job.file.sectors]:
        actual_address = addr - SECTOR_SIZE
        with lock:
            #indexes = [index for index, entry in enumerate(job.file.sectors) if entry[0] == inp]
            for i in indexes:
                job.file.address_table[i].append(actual_address)
                job.file.remaining_sectors[i] = None
                job.success_signal.emit(i)
        if close_reader:
            close_reader.success_count += 1
        elif not job.primary_reader.inspection_in_progress(addr):
            job.begin_close_inspection(actual_address)
        #if not job.finished and not [index for index, entry in enumerate(job.file.sectors) if not entry[1]]:
        if not job.finished and not any(job.file.remaining_sectors):
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
        self.perf = InspectionPerformanceCalc(self.sector_limit)
        job.perf.children.append(self.perf)
        # TODO increase perf total because we have just added self.sector_limit sectors to check....

    def read(self, addr):
        current_thread().name = ("Close reader at " + hex(addr))
        self.fd.seek(addr)
        self.perf.start()
        for _ in range(self.sector_limit):
            data = self.fd.read(SECTOR_SIZE)
            if job.finished or not data:
                break
            if data not in MEANINGLESS_SECTORS or self.success_count > (self.sector_count / 2):
                executor.submit(check_sector, data, self.fd.tell(), self)
            self.sector_count += 1
            executor.submit(self.perf.increment)
        return

class ForwardCloseReader(CloseReader):
    def read(self, addr):
        super().read(addr)
        with lock:
            job.perf.children.remove(self.perf)
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a forward inspection at " + hex(addr))
        return


class BackwardCloseReader(CloseReader):
    def read(self, addr):
        super().read(addr - (self.sector_limit * SECTOR_SIZE))
        with lock:
            job.perf.children.remove(self.perf)
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a backward inspection at " + hex(addr))
        return

class PrimaryReader(DiskReader):

    def __init__(self, disk_path, total_sectors, jump_size):
        super().__init__(disk_path)
        self.jump_size = jump_size * SECTOR_SIZE
        self.inspections = []       

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))
        while self.inspections:
            print('Waiting for close inspections to complete before resuming express search at address ' + hex(self.fd.tell()))
            time.sleep(3)
        job.perf.start()
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
    ready_signal = QtCore.pyqtSignal(bool)

    def update_log(self):
        for i in range(len(self.rebuilt_file)):
            self.log.write("Sector " + i + ":\t\t" + self.rebuilt_file[i][0])

    def begin_close_inspection(self, addr):
        inspection = self.close_inspection(addr)
        self.new_inspection_signal.emit(inspection)

    def test_run(self):
        def fake_function(self, inp):
            _  = [i for i, sector in enumerate(job.file.remaining_sectors) if sector == inp]
        
        test_perf = ExpressPerformanceCalc(self.primary_reader.jump_size, self.diskSize.total, SECTOR_SIZE)
        self.primary_reader.fd.seek(0)
        test_perf.start()
        for _ in range(test_perf.sample_size):
            print(_)
            data = self.primary_reader.fd.read(SECTOR_SIZE)
            executor.submit(fake_function, data)
            test_perf.increment()
            self.primary_reader.fd.seek(self.primary_reader.jump_size, 1)
        return test_perf.avg

    def begin(self, start_at):
        current_thread().name = "Main program thread"
        init_avg = self.test_run()
        self.perf = ExpressPerformanceCalc(self.primary_reader.jump_size, self.diskSize.total, SECTOR_SIZE, init_avg)
        self.ready_signal.emit(True)
        self.primary_reader.read(start_at)

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
        fd = os.fdopen(os.open(self.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')
        out_file = open(self.rebuilt_file_path, 'wb')
        """ for addr, sector in self.rebuilt_file:
            out_file.write(sector) """
        c = 0
        for addresses in job.file.address_table:
            fd.seek(addresses[0])
            out_file.write(fd.read(SECTOR_SIZE))
            out_file.flush()
            c += 1
        out_file.close()
        self.finished_signal.emit(True)

    def __init__(self, vol, file, do_logging, express):
        super().__init__()
        self.finished = False
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.diskSize = disk_usage(vol + ':\\')
        self.file = file
        self.done_sectors = 0
        self.total_sectors = len(file.remaining_sectors)
        self.rebuilt_file = [None] * self.total_sectors
        #self.finished_signal.connect(self.build_file)

        if express == True:
            skip_size = self.total_sectors // 2
            self.primary_reader = PrimaryReader(self.disk_path, self.total_sectors, skip_size)
        else:
            pass
            # TODO remove option

        if do_logging == True:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.file.name + ".log", 'w')
        else:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")

        self.rebuilt_file_path = self.dir_name + '/' + self.file.name.split('.')[0] + "_RECONSTRUCTED." + self.file.name.split('.')[1]




class SourceFile():
    def __init__(self, path):
        self.remaining_sectors = self.to_sectors(path)
        self.address_table = [[] for _ in range(len(self.remaining_sectors))]
        #self.remaining_sectors = copy.deepcopy(self.sectors)
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    """ def get_unique_sector_index(self, sector):

        occurrences = [i for i, s in enumerate(self.sectors) if s == sector] # get all occurences of this data
        if len(occurrences) > 1:
            for index in occurrences:
                if job.rebuilt_file[index] == None:
                    return index
        else:
            return occurrences[0] """


    def to_sectors(self, path):
        f = open(path, "rb")
        f.seek(0)
        result = []
        while True:
            cur = f.read(SECTOR_SIZE)
            if cur == b'':
                break
            elif len(cur) == SECTOR_SIZE:
                result.append(cur)
            else:
                result.append((bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1]))))   #trailing sector zfill
        return result

def initialize_job(do_logging, express, selected_vol, file, ex):
    global executor
    executor = ex
    global job
    job = Job(selected_vol, file, do_logging, express)
    return job

