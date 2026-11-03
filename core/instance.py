"""A second launch activates the running application without killing it."""

import hashlib

from PySide6.QtCore import QObject, QLockFile, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from poppy.core.storage import data_dir


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        identity = str(directory.resolve()).casefold().encode("utf-8")
        self._name = "poppy-" + hashlib.sha256(identity).hexdigest()[:20]
        self._lock = QLockFile(str(directory / "instance.lock"))
        self._lock.setStaleLockTime(0)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._activate)

    def acquire(self) -> bool:
        if not self._lock.tryLock(0):
            if self._lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError("Poppy cannot create its instance lock.")
            socket = QLocalSocket()
            socket.connectToServer(self._name)
            socket.waitForConnected(1000)
            socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self._name):
            self._lock.unlock()
            raise OSError(self._server.errorString())
        return True

    def _activate(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activation_requested.emit()

    def close(self):
        self._server.close()
        self._lock.unlock()
