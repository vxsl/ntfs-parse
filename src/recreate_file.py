import time, os
from shutil import disk_usage
from threading import Lock, current_thread
from multiprocessing import cpu_count
from PyQt5 import QtCore
from performance import PerformanceCalculator, InspectionPerformanceCalc

SECTOR_SIZE = 512
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]

lock = Lock()
threadpool = QtCore.QThreadPool.globalInstance()
threadpool.setMaxThreadCount(cpu_count() - 3)

class Worker(QtCore.QRunnable):

    def __init__(self, fn, *args):
        super(Worker, self).__init__()

        if not fn:
            self.fn = self.check_sector 
        else:
            self.fn = fn
        self.args = args

    @QtCore.pyqtSlot()
    def run(self):
        self.fn(*self.args)

    @QtCore.pyqtSlot()
    def check_sector(self, inp, addr, close_reader=None):
        try:
            i = job.file.remaining_sectors.index(inp)
            actual_address = addr - SECTOR_SIZE
            job.file.address_table[i].append(actual_address)
            job.file.remaining_sectors[i] = None
            if len(job.file.address_table[i]) == 1:
                job.done_sectors += 1
                job.success_signal.emit(i)
            if close_reader:
                close_reader.success_count += 1
                close_reader.consecutive_successes += 1
            elif not job.skim_reader.inspection_in_progress(addr):
                job.CloseInspection(actual_address)
            if all(_ in MEANINGLESS_SECTORS for _ in filter(None, job.file.remaining_sectors)) \
                and not job.finished:
                with lock:
                    job.finish()
        except ValueError:  # inp did not exist in job.file.remaining_sectors
            if close_reader:
                close_reader.consecutive_successes = 0
        return

class DiskReader(QtCore.QObject):
    def __init__(self, disk_path):
        super().__init__()
        self.fobj = os.fdopen(os.open(disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):

    progress_signal = QtCore.pyqtSignal(tuple)
    finished_signal = QtCore.pyqtSignal()

    def __init__(self, start_at, backward=False):
        super().__init__(job.disk_path)
        self.start_at = start_at
        self.sector_limit = job.total_sectors 
        self.sector_count = 0
        self.success_count = 0
        self.consecutive_successes = 0
        if backward:
            self.id_tuple = ("backward", start_at, hex(start_at))
            self.start_at -= (self.sector_limit * SECTOR_SIZE)
        else:
            self.id_tuple = ("forward", start_at, hex(start_at))
        self.perf = InspectionPerformanceCalc(self.sector_limit, self.id_tuple[0] + self.id_tuple[2])
        job.skim_reader.perf.children.append(self.perf)

    def read(self):
        current_thread().name = self.id_tuple[0] + self.id_tuple[2]
        self.fobj.seek(self.start_at)
        self.perf.start()
        for _ in range(self.sector_limit):
            data = self.fobj.read(SECTOR_SIZE)
            if job.finished or not data:
                break
            if data not in MEANINGLESS_SECTORS or self.consecutive_successes > 2:
                threadpool.start(Worker(None, data, self.fobj.tell(), self))
            self.sector_count += 1
            threadpool.start(Worker(self.emit_progress))
            time.sleep(0.01)
        with lock:
            job.skim_reader.perf.children.remove(self.perf)
            job.skim_reader.inspections.remove(self)
        self.finished_signal.emit()
        current_thread().name = ("X " + self.id_tuple[0] + self.id_tuple[2])
        del self.perf

        if not data:
            job.skim_reader.handle_eof()
        else:
            job.skim_reader.request_resume()
            
        return

    def emit_progress(self):	
        self.perf.increment()	
        self.progress_signal.emit((self.sector_count, self.success_count))        	

class SkimReader(DiskReader):

    new_inspection_signal = QtCore.pyqtSignal(object)
    resumed_signal = QtCore.pyqtSignal()
    progress_signal = QtCore.pyqtSignal(float)

    def __init__(self, disk_path, jump_size, init_address):
        super().__init__(disk_path)
        self.jump_size = jump_size * SECTOR_SIZE
        self.inspections = []
        self.resume_at = None
        self.resuming_flag = False
        self.init_address = init_address
        self.second_pass = False

    def request_resume(self):
        if not self.resuming_flag:
            self.resuming_flag = True
            if self.inspections:
                self.resuming_flag = False
                return
            else:
                self.read(self.resume_at) # only resume if all children are finished
        self.resumed_signal.emit()
    
    def handle_eof(self):
        if self.inspections:
            return
        if self.init_address == 0:
            job.finished = True
            job.finished_signal.emit(False)
        else:
            self.second_pass = True
            self.read(0)

    def read(self, start_at=None):
        if start_at is None:
            start_at = self.init_address 
        current_thread().name = "Skim thread"
        self.fobj.seek(start_at)
        self.perf.start()
        while True:
            data = self.fobj.read(SECTOR_SIZE)
            if self.inspections or job.finished or not data \
                or (self.fobj.tell() > self.init_address and self.second_pass):
                break
            if data not in MEANINGLESS_SECTORS:
                threadpool.start(Worker(None, data, self.fobj.tell()))
            self.progress_signal.emit(self.perf.increment())
            self.fobj.seek(self.jump_size, 1)
        if self.inspections and not job.finished:
            self.resume_at = self.fobj.tell()
            self.resuming_flag = False

        if not data:
            self.handle_eof()
        elif (self.fobj.tell() > self.init_address) and self.second_pass:
            job.finished = True
            job.finished_signal.emit(False)

        current_thread().name = "Control returned from skim thread"

    def inspection_in_progress(self, addr):
        for reader in self.inspections:
            upper_limit = reader.id_tuple[1] + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = reader.id_tuple[1] - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False

class Job(QtCore.QObject):

    success_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(bool)
    loading_progress_signal = QtCore.pyqtSignal(float)
    loading_complete_signal = QtCore.pyqtSignal(tuple)

    def __init__(self, vol, file, init_address):
        super().__init__()

        global job
        job = self

        self.finished = False
        self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
        os.makedirs(self.dir_name, mode=0o755)
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.volume_size = disk_usage(vol + ':\\')
        self.file = file
        self.done_sectors = 0
        self.total_sectors = len(file.remaining_sectors)
        jump_size = self.total_sectors // 2
        self.skim_reader = SkimReader(self.disk_path, jump_size, init_address)
        self.rebuilt_file_path = self.dir_name + '/' + self.file.name.split('.')[0] + "_RECONSTRUCTED." + self.file.name.split('.')[1]

    def test_run(self):
        def fake_fn(inp):
            _  = [i for i, sector in enumerate(job.file.remaining_sectors) if sector == inp]

        test_perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, self.skim_reader.jump_size, sample_size=100)
        insp_sample_size = InspectionPerformanceCalc(SECTOR_SIZE, '').sample_size
        self.skim_reader.fobj.seek(0)
        test_perf.start()
        for _ in range(test_perf.sample_size + 1):
            data = self.skim_reader.fobj.read(SECTOR_SIZE)
            threadpool.start(Worker(fake_fn, data))
            test_perf.increment()
            self.loading_progress_signal.emit(100 * _ / test_perf.sample_size)
            self.skim_reader.fobj.seek(self.skim_reader.jump_size, 1)
        return (insp_sample_size, (test_perf.avg, test_perf.get_remaining_seconds()))

    def run(self):        
        test_results = self.test_run()
        init_avg = test_results[1][0]
        self.skim_reader.perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, self.skim_reader.jump_size, init_avg=init_avg)
        self.loading_complete_signal.emit(test_results)
        self.skim_reader.read()

    class CloseInspection(QtCore.QObject):
        def __init__(self, address):
            super().__init__()
            self.address = address
            self.forward = CloseReader(self.address)
            self.backward = CloseReader(self.address, True)
            job.skim_reader.inspections.append(self.forward)
            job.skim_reader.inspections.append(self.backward)
            job.skim_reader.new_inspection_signal.emit(self)
            threadpool.start(Worker(self.forward.read))
            threadpool.start(Worker(self.backward.read))

    def finish(self):

        self.finished = True

        for sector in filter(None, job.file.remaining_sectors):
            if sector in MEANINGLESS_SECTORS:
                i = job.file.remaining_sectors.index(sector)
                job.file.address_table[i] = sector
                job.file.remaining_sectors[i] = None

        fobj = os.fdopen(os.open(self.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')
        out_file = open(self.rebuilt_file_path, 'wb')
        for addresses in job.file.address_table:
            fobj.seek(addresses[0])
            out_file.write(fobj.read(SECTOR_SIZE))
            out_file.flush()
        out_file.close()
        self.finished_signal.emit(True)

