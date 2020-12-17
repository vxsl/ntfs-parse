import time, os
from shutil import disk_usage
from threading import Lock, current_thread
from PyQt5 import QtCore
from .performance.performance import PerformanceCalculator, InspectionPerformanceCalc
from concurrent import futures
from multiprocessing import cpu_count

SECTOR_SIZE = 512 # bytes
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]
lock = Lock()
job = None
executor = futures.ThreadPoolExecutor(max_workers=(cpu_count() - 3))

def check_sector(inp, addr, close_reader=None):
    try:
        i = job.file.remaining_sectors.index(inp)
        actual_address = addr - SECTOR_SIZE 
        job.file.address_table[i].append(actual_address)
        job.file.remaining_sectors[i] = None
        if len(job.file.address_table[i]) == 1:
            pass
            job.success_signal.emit(i)
        else:
            print('length different')
        if close_reader:
            close_reader.success_count += 1
            close_reader.consecutive_successes += 1
        elif job.primary_reader.express and not job.primary_reader.inspection_in_progress(addr):
            executor.submit(job.begin_close_inspection, actual_address)
        if not any(job.file.remaining_sectors) and not job.finished:
            job.finish()
        return
    except ValueError:  # inp did not exist in job.file.remaining_sectors
        if close_reader:
            close_reader.consecutive_successes = 0
        return
    return


class DiskReader(QtCore.QObject):
    def __init__(self, disk_path):
        super().__init__()
        self.fd = os.fdopen(os.open(disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):

    progress_signal = QtCore.pyqtSignal(dict)
    finished_signal = QtCore.pyqtSignal()

    def __init__(self, start_at):
        super().__init__(job.disk_path)
        self.start_at = start_at
        self.sector_limit = job.total_sectors #???
        self.sector_count = 0
        self.success_count = 0
        self.consecutive_successes = 0
        self.perf = InspectionPerformanceCalc(self.sector_limit)
        self.finished = False
        job.perf.children.append(self.perf)

    def read(self):
        current_thread().name = ("Close reader at " + hex(self.start_at))
        self.fd.seek(self.start_at)
        self.perf.start()
        for sector in range(self.sector_limit):
            data = self.fd.read(SECTOR_SIZE)
            if job.finished or not data or self.should_quit():
                break
            if data not in MEANINGLESS_SECTORS or self.consecutive_successes > 2:
                executor.submit(check_sector, data, self.fd.tell(), self)
            self.sector_count += 1
            executor.submit(self.perf.increment)
            #self.progress_signal.emit()
            #if sector % 10 == 0:
            executor.submit(self.emit_progress)
        self.finished = True
        return

    def emit_progress(self):
        self.progress_signal.emit({
            'sector_count':self.sector_count,
            'success_count':self.success_count,
            'performance':self.perf.get_remaining_estimate()
        })
        job.executor_queue_signal.emit(executor._work_queue.qsize())
    
    def should_quit(self):
        return False
        if self.sector_count > 0.15 * self.sector_limit \
        and self.success_count < 0.25 * self.sector_count \
        and self.consecutive_successes == 0:
            return True
            # TODO store info for later check if all else proves unsuccessful
        else:
            return False

class ForwardCloseReader(CloseReader):
    def read(self):
        super().read()
        with lock:
            job.perf.children.remove(self.perf)
            job.primary_reader.inspections.remove((hex(self.start_at), self))
        self.finished_signal.emit()
        current_thread().name = ("Control returned from a forward inspection at " + hex(self.start_at))
        job.resume_primary_reader_signal.emit()
        return


class BackwardCloseReader(CloseReader):
    def __init__(self, start_at):
        super(BackwardCloseReader, self).__init__(start_at)
        self.start_at -= (self.sector_limit * SECTOR_SIZE)

    def read(self):
        super().read()
        with lock:
            job.perf.children.remove(self.perf)
            job.primary_reader.inspections.remove((hex(self.start_at), self))
        self.finished_signal.emit()
        current_thread().name = ("Control returned from a backward inspection at " + hex(self.start_at))
        job.resume_primary_reader_signal.emit()
        return

class PrimaryReader(DiskReader):

    resume_signal = QtCore.pyqtSignal()

    def __init__(self, disk_path, **kwargs):
        super().__init__(disk_path)
        try:
            self.jump_size = kwargs['jump_size'] * SECTOR_SIZE
            self.express = True
        except KeyError:
            self.jump_size = 0
            self.express = False
        self.inspections = []       
        self.resume_at = None
        self.resume_signal.connect(self.request_resume)

    def request_resume(self):
        if self.inspections:
            return
        else:
            self.read(self.resume_at) # only resume if all children are finished

    def read(self, start_at):
        current_thread().name = "Main program thread"
        self.fd.seek(start_at)
        job.perf.start()

        try:
            while True:
                data = self.fd.read(SECTOR_SIZE)
                if job.finished or not data or self.inspections:
                    break
                if data not in MEANINGLESS_SECTORS:
                    executor.submit(check_sector, data, self.fd.tell())
                executor.submit(job.perf.increment)
                job.skim_progress_signal.emit()
                self.fd.seek(self.jump_size, 1)

            if self.inspections and not job.finished:
                self.resume_at = self.fd.tell()
        except: # TODO what type of exception is raised when fd reads past EOF?
            pass

        #job.finished_signal.emit(False)

    def inspection_in_progress(self, addr):
        for address, reader in self.inspections:
            upper_limit = int(address, 16) + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = int(address, 16) - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False



class Job(QtCore.QObject):

    do_test_run = QtCore.pyqtSignal()
    start = QtCore.pyqtSignal(list) 
    new_inspection_signal = QtCore.pyqtSignal(object)
    # PyQt event signaller
    success_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(bool)
    #ready_signal = QtCore.pyqtSignal(bool)
    skim_progress_signal = QtCore.pyqtSignal()
    loading_progress_signal = QtCore.pyqtSignal(float)
    loading_complete_signal = QtCore.pyqtSignal(float)
    executor_queue_signal = QtCore.pyqtSignal(int)

    def __init__(self, vol, file, do_logging, express):
        super().__init__()
        self.do_test_run.connect(self.test_run)
        self.start.connect(self.run)
        self.finished = False
        self.loading_progress = 0
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.volume_size = disk_usage(vol + ':\\')
        self.file = file
        self.done_sectors = 0
        self.total_sectors = len(file.remaining_sectors)
        self.rebuilt_file = [None] * self.total_sectors
        #self.finished_signal.connect(self.build_file)

        if express:
            jump_size = self.total_sectors // 2
            self.primary_reader = PrimaryReader(self.disk_path, jump_size=jump_size)
        else:
            self.primary_reader = PrimaryReader(self.disk_path)

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

    def update_log(self):
        for i in range(len(self.rebuilt_file)):
            self.log.write("Sector " + i + ":\t\t" + self.rebuilt_file[i][0])

    @QtCore.pyqtSlot()
    def test_run(self):
        def fake_function(inp):
            _  = [i for i, sector in enumerate(job.file.remaining_sectors) if sector == inp]
        
        if self.primary_reader.express:
            test_perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, sample_size=100, jump_size=self.primary_reader.jump_size)
        else:
            test_perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, sample_size=100)

        self.primary_reader.fd.seek(0)
        test_perf.start()
        for _ in range(test_perf.sample_size + 1):
            data = self.primary_reader.fd.read(SECTOR_SIZE)
            executor.submit(fake_function, data)
            test_perf.increment()
            #self.loading_progress = 100 * _ / test_perf.sample_size
            self.loading_progress_signal.emit(100 * _ / test_perf.sample_size)
            self.primary_reader.fd.seek(self.primary_reader.jump_size, 1)
        self.loading_complete_signal.emit(test_perf.avg)

    @QtCore.pyqtSlot(list)
    def run(self, params): 
        start_at = params[0]
        init_avg = params[1]  
        if self.primary_reader.express:
            self.perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, jump_size=self.primary_reader.jump_size, init_avg=init_avg) # TODO implement kwargs so we don't have to put 1000 here
        else:
            self.perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, init_avg=init_avg)
        self.primary_reader.read(start_at)

    class CloseInspection(QtCore.QObject):

        def __init__(self, addr):
            self.addr = addr
            self.forward = ForwardCloseReader(addr)
            self.backward = BackwardCloseReader(addr)
            job.primary_reader.inspections.append((hex(self.addr), self.forward))
            job.primary_reader.inspections.append((hex(self.addr), self.backward))
            executor.submit(self.forward.read)
            executor.submit(self.backward.read)            
        
        """ def start(self):
            fwd = self.forward
            bkwd = self.backward
            while not fwd.finished and not bkwd.finished:
                if not fwd.finished:
                    fwd.progress_signal.emit()
                if not bkwd.finished:
                    bkwd.progress_signal.emit()
                time.sleep(2)
            print("Inspections finished") """

    def begin_close_inspection(self, addr):
        inspection = self.CloseInspection(addr)
        self.new_inspection_signal.emit(inspection)
        #inspection.start()

    def finish(self):
        with lock:
            self.finished = True
            fd = os.fdopen(os.open(self.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')
            out_file = open(self.rebuilt_file_path, 'wb')
            """ for addr, sector in self.rebuilt_file:
                out_file.write(sector) """
            for addresses in job.file.address_table:
                fd.seek(addresses[0])
                out_file.write(fd.read(SECTOR_SIZE))
                out_file.flush()
            out_file.close()
            self.finished_signal.emit(True)

class SourceFile():
    def __init__(self, path):
        self.remaining_sectors = self.to_sectors(path)
        self.address_table = [[] for _ in range(len(self.remaining_sectors))]
        #self.remaining_sectors = copy.deepcopy(self.sectors)
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]


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

def initialize_job(do_logging, selected_vol, file, express):
    global job
    job = Job(selected_vol, file, do_logging, express)
    return job

