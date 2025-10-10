import threading
from time import monotonic


class LightSwitch:
    """
    An auxiliary "light switch"-like object. The first thread to acquire the
    switch also acquires the *lock* associated with the switch. The last thread
    to release the switch also releases the lock associated with the switch.

    If the first and last threads can differ, you must use a primitive
    :class:`threading.Lock` or :class:`threading.Semaphore` (initialized to 1)
    as the value of the *lock* parameter. If the first and last threads will
    always be the same, you *may* use a re-entrant :class:`threading.RLock`.

    This implementation is based on [1]_, sec. 4.2.2 but with additions to
    permit non-blocking execution or timeouts in blocking mode, and operation
    as a context manager.

    .. [1] A.B. Downey: "The little book of semaphores", Version 2.2.1, 2016
       https://greenteapress.com/wp/semaphores/
    """
    def __init__(self, lock):
        self._counter = 0
        self._lock = lock
        self._mutex = threading.Lock()

    def acquire(self, blocking=True, timeout=-1):
        start = monotonic()
        if not self._mutex.acquire(blocking=blocking, timeout=timeout):
            return False
        try:
            self._counter += 1
            if self._counter == 1:
                timeout = (
                    -1 if timeout == -1 else
                    max(0, timeout - (monotonic() - start)))
                if self._lock.acquire(blocking=blocking, timeout=timeout):
                    return True
                else:
                    self._counter = 0
                    return False
            else:
                return True
        finally:
            self._mutex.release()

    def release(self):
        with self._mutex:
            if not self._counter:
                raise RuntimeError('Attempt to release an unacquired Switch')
            self._counter -= 1
            if self._counter == 0:
                self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


class RWLock:
    """
    Synchronization object used in a solution of so-called second
    readers-writers problem.

    In this problem, many readers can simultaneously access a share, and a
    writer has an exclusive access to this share. Additionally, the following
    constraints should be met:

    1. no reader should be kept waiting if the share is currently opened for
       reading unless a writer is also waiting for the share,

    2. no writer should be kept waiting for the share longer than absolutely
       necessary.

    The implementation is based on [1]_, secs. 4.2.2, 4.2.6 with modifications
    for a more "Pythonic" style. The class provides two objects, ``read`` and
    ``write`` which each support the context manager protocol along with the
    typical ``acquire`` and ``release`` methods.

    .. [1] A.B. Downey: "The little book of semaphores", Version 2.2.1, 2016
    """

    def __init__(self):
        block_writers = threading.Lock()
        block_readers = threading.Lock()
        read_switch = LightSwitch(block_writers)
        self.read = _ReadLock(read_switch, block_readers)
        self.write = _WriteLock(block_readers, block_writers)


class _ReadLock:
    def __init__(self, read_switch, block_readers):
        self._read_switch = read_switch
        self._block_readers = block_readers

    def acquire(self):
        # NOTE: The block_readers lock *appears* pointless, but blocks the
        # read lock acquisition when a writer holds it (see _WriteLock.acquire)
        with self._block_readers:
            pass
        self._read_switch.acquire()

    def release(self):
        self._read_switch.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


class _WriteLock:
    def __init__(self, block_readers, block_writers):
        self._block_readers = block_readers
        self._block_writers = block_writers

    def acquire(self):
        # NOTE: The read_switch acquires block_writers. Hence, when 1 or more
        # readers have acquired read_switch, block_writers is acquired also
        self._block_readers.acquire()
        self._block_writers.acquire()

    def release(self):
        self._block_readers.release()
        self._block_writers.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
