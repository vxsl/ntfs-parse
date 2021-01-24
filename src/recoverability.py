import time
import os
from shutil import disk_usage
from threading import Lock, current_thread
from PyQt5 import QtCore
from performance import PerformanceCalculator, InspectionPerformanceCalc, SAMPLE_WINDOW

# constants
SECTOR_SIZE = 512
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]

# globals
inspection_manipulation_mutex = Lock()
threadpool = QtCore.QThreadPool.globalInstance()

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
                job.new_close_inspection(actual_address)
            if all(_ in MEANINGLESS_SECTORS for _ in filter(None, job.file.remaining_sectors)) \
                and not job.finished:
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
    finished_signal = QtCore.pyqtSignal(float)

    def __init__(self, start_at, backward=False):
        super().__init__(job.disk_path)
        self.start_at = start_at
        self.sector_limit = job.total_sectors // 2
        self.sector_count = 0
        self.success_count = 0
        self.consecutive_successes = 0
        if backward:
            self.id_tuple = ("backward", start_at, hex(start_at))
            self.start_at -= (self.sector_limit * SECTOR_SIZE)
        else:
            self.id_tuple = ("forward", start_at, hex(start_at))
        self.perf = InspectionPerformanceCalc(self.sector_limit, self.id_tuple[0] + self.id_tuple[2])

    def read(self):
        #debug_this_thread()
        current_thread().name = self.id_tuple[0] + self.id_tuple[2]
        self.fobj.seek(self.start_at)
        for _ in range(self.sector_limit):
            data = self.fobj.read(SECTOR_SIZE)
            if job.finished or not data:
                break
            if data not in MEANINGLESS_SECTORS or self.consecutive_successes > 2:
                threadpool.start(Worker(None, data, self.fobj.tell(), self))
            self.sector_count += 1
            self.progress_signal.emit((self.perf.increment(), self.success_count / self.sector_count))

            time.sleep(0.01)

        if job.finished:
            return

        inspection_manipulation_mutex.acquire()
        job.skim_reader.inspections.remove(self)
        inspection_manipulation_mutex.release()

        if not data:
            job.skim_reader.handle_eof()
        else:
            new_insp_address = self.fobj.tell() + (self.sector_limit * SECTOR_SIZE)
            if (self.consecutive_successes > 0 or (self.success_count / self.sector_count) > 0.4) \
                and not job.skim_reader.inspection_in_progress(new_insp_address):
                job.new_close_inspection(new_insp_address)
            else:
                #print('request')
                job.skim_reader.request_resume()

        self.finished_signal.emit(self.success_count / self.sector_count)
        #print(self.id_tuple[0] + self.id_tuple[2] + " EMIT")
        current_thread().name = ("X " + self.id_tuple[0] + self.id_tuple[2])
        del self.perf

        return

class SkimReader(DiskReader):

    new_inspection_signal = QtCore.pyqtSignal(tuple)
    progress_signal = QtCore.pyqtSignal(float)
    resuming_signal = QtCore.pyqtSignal()

    def __init__(self, disk_path, jump_sectors, init_address):
        super().__init__(disk_path)
        self.jump_size = jump_sectors * SECTOR_SIZE
        self.inspections = []
        self.resume_at = None
        self.init_address = init_address
        self.second_pass = False
        self.perf = None

    def request_resume(self):
        inspection_manipulation_mutex.acquire()
        if not self.inspections: # only resume if all children are finished
            self.resuming_signal.emit()
            threadpool.start(Worker(self.read, self.resume_at))
        inspection_manipulation_mutex.release()


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

        while True:
            data = self.fobj.read(SECTOR_SIZE)
            if self.inspections or job.finished or not data \
                or (self.fobj.tell() > self.init_address and self.second_pass):
                break
            if data not in MEANINGLESS_SECTORS:
                threadpool.start(Worker(None, data, self.fobj.tell()))
            self.progress_signal.emit(self.perf.increment())
            self.fobj.seek(self.jump_size, 1)

        if job.finished:
            return
        elif self.inspections:
            self.resume_at = self.fobj.tell()

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
            if lower_limit < addr and addr < upper_limit:
                return True
        return False

class Job(QtCore.QObject):

    success_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(tuple)
    test_run_progress_signal = QtCore.pyqtSignal(float)
    test_run_finished_signal = QtCore.pyqtSignal()

    def __init__(self, vol, file, init_address):
        super().__init__()

        global job
        job = self

        self.finished = False
        self.dir_name = 'recoverability/' + time.ctime().replace(":", '_')
        os.makedirs(self.dir_name, mode=0o755)
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.volume_size = disk_usage(vol + ':\\')
        self.file = file
        self.done_sectors = 0
        self.total_sectors = len(file.remaining_sectors)
        self.jump_sectors = self.total_sectors // 2
        self.skim_reader = SkimReader(self.disk_path, self.jump_sectors, init_address)
        self.rebuilt_file_path = self.dir_name + '/' + self.file.name.split('.')[0] + " [reconstructed using sectors from " + vol + "]." + self.file.name.split('.')[1]


    def test_run(self):
        #debug_this_thread()
        def fake_fn(inp):
            _  = [i for i, sector in enumerate(job.file.remaining_sectors) if sector == inp]

        test_window = 0.5

        self.skim_reader.fobj.seek(0)
        start = time.perf_counter()
        skips = 0
        while True:
            data = self.skim_reader.fobj.read(SECTOR_SIZE)
            threadpool.start(Worker(fake_fn, data))
            skips += 1
            progress = (time.perf_counter() - start) / test_window
            if progress >= 1:
                break
            self.test_run_progress_signal.emit(100 * progress)
            self.skim_reader.fobj.seek(self.skim_reader.jump_size, 1)

        avg = skips * SAMPLE_WINDOW / test_window
        return avg

    def run(self):
        init_avg = self.test_run()
        self.skim_reader.perf = PerformanceCalculator(self.volume_size.total, self.skim_reader.jump_size, self.jump_sectors, init_avg=init_avg)
        self.test_run_finished_signal.emit()
        self.skim_reader.read()

    def new_close_inspection(self, address):
        inspection_manipulation_mutex.acquire()
        forward = CloseReader(address)
        backward = CloseReader(address, True)
        job.skim_reader.inspections.append(forward)
        job.skim_reader.inspections.append(backward)
        job.skim_reader.new_inspection_signal.emit((address, forward, backward))
        inspection_manipulation_mutex.release()
        threadpool.start(Worker(forward.read))
        threadpool.start(Worker(backward.read))

    def finish(self):

        self.finished = True
        auto_filled = 0
        for sector in filter(None, job.file.remaining_sectors):
            if sector in MEANINGLESS_SECTORS:
                i = job.file.remaining_sectors.index(sector)
                job.file.address_table[i] = sector
                job.file.remaining_sectors[i] = None
                auto_filled += 1

        fobj = os.fdopen(os.open(self.disk_path, os.O_RDONLY | os.O_BINARY), 'rb')
        out_file = open(self.rebuilt_file_path, 'wb')
        for addresses in job.file.address_table:
            fobj.seek(addresses[0])
            out_file.write(fobj.read(SECTOR_SIZE))
            out_file.flush()
        out_file.close()
        self.finished_signal.emit((True, auto_filled))

