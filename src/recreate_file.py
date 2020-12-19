import time, os
from shutil import disk_usage
from threading import Lock, current_thread
from concurrent import futures
from multiprocessing import cpu_count
from PyQt5 import QtCore
from performance import PerformanceCalculator, InspectionPerformanceCalc

lock = Lock()
executor = futures.ThreadPoolExecutor(max_workers=(cpu_count() - 3))

def check_sector(inp, addr, close_reader=None):
    try:
        i = job.file.remaining_sectors.index(inp)
        actual_address = addr - SECTOR_SIZE
        job.file.address_table[i].append(actual_address)
        job.file.remaining_sectors[i] = None
        if len(job.file.address_table[i]) == 1:
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
        return
    except ValueError:  # inp did not exist in job.file.remaining_sectors
        if close_reader:
            close_reader.consecutive_successes = 0
        return
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
        self.sector_limit = job.total_sectors #???
        self.sector_count = 0
        self.success_count = 0
        self.consecutive_successes = 0
        if backward:
            self.id_str = "bkwd" + hex(start_at)
        else:
            self.id_str = "fwd" + hex(start_at)
        self.perf = InspectionPerformanceCalc(self.sector_limit, self.id_str)
        job.perf.children.append(self.perf)

    def read(self):
        current_thread().name = self.id_str
        self.fobj.seek(self.start_at)
        self.perf.start()
        for _ in range(self.sector_limit):
            data = self.fobj.read(SECTOR_SIZE)
            if job.finished or not data:
                break
            if data not in MEANINGLESS_SECTORS or self.consecutive_successes > 2:
                executor.submit(check_sector, data, self.fobj.tell(), self)
            self.sector_count += 1
            executor.submit(self.perf.increment)
            executor.submit(self.emit_progress)
        return

    def emit_progress(self):
        self.progress_signal.emit((self.sector_count, self.success_count))
        job.executor_queue_signal.emit(executor._work_queue.qsize())

class ForwardCloseReader(CloseReader):
    def read(self):
        super().read()
        with lock:
            job.perf.children.remove(self.perf)
            job.skim_reader.inspections.remove((hex(self.start_at), self))
        self.finished_signal.emit()
        current_thread().name = ("Control returned from " + self.id_str)
        job.skim_reader.request_resume()

class BackwardCloseReader(CloseReader):
    def __init__(self, start_at):
        super(BackwardCloseReader, self).__init__(start_at, True)
        self.start_at -= (self.sector_limit * SECTOR_SIZE)

    def read(self):
        super().read()
        with lock:
            job.perf.children.remove(self.perf)
            job.skim_reader.inspections.remove((hex(self.start_at), self))
        self.finished_signal.emit()
        current_thread().name = ("Control returned from " + self.id_str)
        job.skim_reader.request_resume()

class SkimReader(DiskReader):

    resume_signal = QtCore.pyqtSignal()

    def __init__(self, disk_path, jump_size, **kwargs):
        super().__init__(disk_path)
        self.jump_size = jump_size * SECTOR_SIZE
        self.inspections = []
        self.resume_at = None
        self.resume_signal.connect(self.request_resume)
        self.resuming_flag = False

    def request_resume(self):
        if not self.resuming_flag:
            self.resuming_flag = True
            if self.inspections:
                self.resuming_flag = False
                return
            else:
                self.read(self.resume_at) # only resume if all children are finished

    def read(self, start_at):
        current_thread().name = "Skim thread"
        self.fobj.seek(start_at)
        job.perf.start()

        try:
            while True:
                data = self.fobj.read(SECTOR_SIZE)
                if self.inspections or job.finished or not data:
                    break
                if data not in MEANINGLESS_SECTORS:
                    executor.submit(check_sector, data, self.fobj.tell())
                executor.submit(job.perf.increment)
                job.skim_progress_signal.emit()
                self.fobj.seek(self.jump_size, 1)

            if self.inspections and not job.finished:
                self.resume_at = self.fobj.tell()
                self.resuming_flag = False
        except: # TODO what type of exception is raised when fd reads past EOF?
            pass
        current_thread().name = "Control returned from skim thread"
        #job.finished_signal.emit(False)

    def inspection_in_progress(self, addr):
        for address, reader in self.inspections:
            upper_limit = int(address, 16) + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = int(address, 16) - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False

class Job(QtCore.QObject):

    new_inspection_signal = QtCore.pyqtSignal(object)
    success_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(bool)
    skim_progress_signal = QtCore.pyqtSignal()
    loading_progress_signal = QtCore.pyqtSignal(float)
    loading_complete_signal = QtCore.pyqtSignal(tuple)
    executor_queue_signal = QtCore.pyqtSignal(int)
    perf_created_signal = QtCore.pyqtSignal()

    def __init__(self, vol, file, sector_size, start_at):
        super().__init__()

        global SECTOR_SIZE
        SECTOR_SIZE = sector_size
        global MEANINGLESS_SECTORS
        MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]
        global job
        job = self

        self.finished = False
        self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
        os.makedirs(self.dir_name, mode=0o755)
        self.loading_progress = 0
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.volume_size = disk_usage(vol + ':\\')
        self.start_at = start_at
        self.file = file
        self.done_sectors = 0
        self.perf = None
        self.total_sectors = len(file.remaining_sectors)
        self.rebuilt_file = [None] * self.total_sectors

        jump_size = self.total_sectors // 2
        self.skim_reader = SkimReader(self.disk_path, jump_size)

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
            executor.submit(fake_fn, data)
            test_perf.increment()
            self.loading_progress_signal.emit(100 * _ / test_perf.sample_size)
            self.skim_reader.fobj.seek(self.skim_reader.jump_size, 1)
        self.loading_complete_signal.emit((insp_sample_size, (test_perf.avg, test_perf.get_remaining_seconds())))
        return test_perf.avg

    def run(self):        
        init_avg = self.test_run() * 10
        self.perf = PerformanceCalculator(self.volume_size.total, SECTOR_SIZE, self.skim_reader.jump_size, init_avg=init_avg)
        self.perf_created_signal.emit()
        self.skim_reader.read(self.start_at)

    class CloseInspection(QtCore.QObject):
        def __init__(self, addr):
            super().__init__()
            self.addr = addr
            self.forward = ForwardCloseReader(addr)
            self.backward = BackwardCloseReader(addr)
            job.skim_reader.inspections.append((hex(self.addr), self.forward))
            job.skim_reader.inspections.append((hex(self.addr), self.backward))
            job.new_inspection_signal.emit(self)
            executor.submit(self.forward.read)
            executor.submit(self.backward.read)

    def finish(self):

        self.finished = True

        for sector in filter(None, job.file.remaining_sectors):
            if sector in MEANINGLESS_SECTORS:
                i = job.file.remaining_sectors.index(sector)
                job.file.address_table[i] = sector
                job.file.remaining_sectors[i] = None

        fobj = os.fdopen(os.open(self.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')
        out_file = open(self.rebuilt_file_path, 'wb')
        """ for addr, sector in self.rebuilt_file:
            out_file.write(sector) """
        for addresses in job.file.address_table:
            fobj.seek(addresses[0])
            out_file.write(fobj.read(SECTOR_SIZE))
            out_file.flush()
        out_file.close()
        self.finished_signal.emit(True)

