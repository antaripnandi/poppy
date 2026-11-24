"""Watch one local destination for new files that have finished writing."""

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from stat import S_ISREG
from threading import Event, Thread

from PySide6.QtCore import QObject, Signal


_PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp", ".aria2",
                     ".!qb", ".!ut", ".bc!", ".opdownload", ".filepart")


def default_download_folder():
    try:
        from win32com.shell import shell, shellcon
        return Path(shell.SHGetKnownFolderPath(shellcon.FOLDERID_Downloads, 0, None))
    except (ImportError, OSError):
        return Path.home() / "Downloads"


def _snapshot(folder):
    files = {}
    partials = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            name = entry.name
            suffix = next((item for item in _PARTIAL_SUFFIXES if name.casefold().endswith(item)), None)
            try:
                if suffix:
                    partials[name[:-len(suffix)]] = entry.stat(follow_symlinks=False).st_size
                    continue
                # Windows DirEntry.stat reports a zero file ID.
                current = os.lstat(entry.path)
            except FileNotFoundError:
                continue
            if S_ISREG(current.st_mode):
                files[name] = _file_stamp(current)
    return files, partials


def _file_stamp(current):
    return current.st_ino, current.st_size, current.st_mtime_ns


def _writer_closed(path):
    # Request read access so Windows checks sharing, then close without
    # reading content. Omitting FILE_SHARE_WRITE detects open writers.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    handle = open_file(str(path), 0x80000000, 0x5, None, 3, 0x00200000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return False
    close_handle = kernel.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(handle)
    return True


class DownloadWatcher(QObject):
    files_ready = Signal(object)
    activity_changed = Signal()
    _found = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder = None
        self.partials = ()
        self.recent = []
        self._stop = None
        self._found.connect(self._deliver)

    def configure(self, enabled, folder=""):
        target = (Path(folder) if folder else default_download_folder()) if enabled else None
        if target == self.folder:
            return
        self.close()
        self.folder = target
        if target is not None:
            self._stop = Event()
            Thread(target=self._watch, args=(target, self._stop), daemon=True, name="poppy-downloads").start()
        self.activity_changed.emit()

    def close(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None
        self.folder = None
        self.partials = ()
        self.recent.clear()

    def _deliver(self, stop, paths, partials):
        if stop is not self._stop or stop.is_set():
            return
        self.partials = partials
        for path in paths:
            self.recent = [entry for entry in self.recent if entry != path]
            self.recent.insert(0, path)
        del self.recent[20:]
        self.activity_changed.emit()
        if paths:
            self.files_ready.emit(paths)

    def _watch(self, folder, stop):
        baseline = None
        pending = {}
        displayed_partials = ()
        while not stop.is_set():
            try:
                files, partials = _snapshot(folder)
            except FileNotFoundError:
                baseline = {}
                pending.clear()
                files, partials = {}, {}
            except OSError:
                stop.wait(2)
                continue
            paths = []
            if baseline is None:
                baseline = files
            else:
                paths = self._scan(folder, files, partials, baseline, pending)
            activity = tuple(sorted(partials.items(), key=lambda item: item[0].casefold())[:20])
            if (paths or activity != displayed_partials) and not stop.is_set():
                displayed_partials = activity
                try:
                    self._found.emit(stop, paths, activity)
                except RuntimeError:
                    return  # The Qt parent was destroyed during shutdown.
            stop.wait(2)

    @staticmethod
    def _scan(folder, files, partials, baseline, pending):
        ready = []
        partial_names = {name.casefold() for name in partials}
        for name in baseline.keys() - files.keys():
            del baseline[name]
        for name in pending.keys() - files.keys():
            del pending[name]
        for name, stamp in files.items():
            if name in baseline and baseline[name][0] == stamp[0]:
                continue
            if name.casefold() in partial_names:
                pending.pop(name, None)
                continue
            previous, count = pending.get(name, (None, 0))
            count = count + 1 if stamp == previous else 0
            pending[name] = (stamp, count)
            path = folder / name
            if count < 2 or not _writer_closed(path):
                continue
            try:
                current = path.lstat()
            except OSError:
                continue
            # The name may point to a different file by the time the probe succeeds.
            if not S_ISREG(current.st_mode) or stamp != _file_stamp(current):
                continue
            baseline[name] = stamp
            del pending[name]
            ready.append(path)
        return ready
