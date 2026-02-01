import threading
from time import monotonic
from contextlib import contextmanager


def remaining(timeout, start):
    """
    Calculate the amount of *timeout* remaining if the routine started at
    *start* (measured by :func:`time.monotonic`).

    If *timeout* is -1 (meaning infinite timeout), this function always returns
    -1. Otherwise, the time remaining is calculated and clamped to 0.
    """
    return (
        -1 if timeout == -1 else
        max(0, timeout - (monotonic() - start)))



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
        if not self._mutex.acquire(blocking, timeout):
            return False
        try:
            self._counter += 1
            if self._counter == 1:
                if self._lock.acquire(blocking, remaining(timeout, start)):
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


class RWLockState:
    """
    State of a thread in :class:`RWLock`. This tracks the number of re-entrant
    calls a thread has made.

    Consider a hypothetical thread performing a series of operations. The
    values that its RWLockState move through will be as follows:

    +---------------+------+-------+---------+-----------+
    | Operation     | read | write | ignored | Notes     |
    +===============+======+=======+=========+===========+
    |               | 0    | 0     | 0       | start     |
    +---------------+------+-------+---------+-----------+
    | read.acquire  | 1    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | read.acquire  | 2    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | read.acquire  | 3    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | write.acquire | 3    | 1     | 0       | upgrade   |
    +---------------+------+-------+---------+-----------+
    | write.acquire | 3    | 2     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | read.acquire  | 3    | 2     | 1       | ignore    |
    +---------------+------+-------+---------+-----------+
    | read.acquire  | 3    | 2     | 2       |           |
    +---------------+------+-------+---------+-----------+
    | read.release  | 3    | 2     | 1       |           |
    +---------------+------+-------+---------+-----------+
    | read.release  | 3    | 2     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | write.release | 3    | 1     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | write.release | 3    | 0     | 0       | downgrade |
    +---------------+------+-------+---------+-----------+
    | read.release  | 2    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | read.release  | 1    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+
    | read.release  | 0    | 0     | 0       |           |
    +---------------+------+-------+---------+-----------+

    upgrade
        At this point this thread holds three re-entrant acquisitions of the
        read lock, but has requested a write lock (effectively requesting to
        upgrade its lock). What this does is release all the read locks held
        (actually one lightswitch release), and start a write lock acquisition

    ignore
        If a thread holds any write locks (whether through upgrade, or because
        it originally grabbed a write lock) all attempted acquisitions of a
        read lock are ignored (but counted)

    downgrade
        Here a thread has released its last write lock while in an upgraded
        state. The implementation will release the write lock then re-acquire
        the number of read-locks specified (actually one lightswitch
        acquisition)
    """
    __slots__ = ('read', 'write', 'ignored')

    def __init__(self):
        self.read = 0
        self.write = 0
        self.ignored = 0

    def __repr__(self):
        return (
            f'{self.__class__.__name__}('
            f'read={self.read}, write={self.write}, ignored={self.ignored})')


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
    for a more "Pythonic" style, and re-entrancy. The class provides two
    objects, :attr:`read` and :attr:`write` which each support the context
    manager protocol along with the typical ``acquire`` and ``release``
    methods.

    Unlike the implementation in the book, both ``read`` and ``write`` are
    re-entrant (in the book version, ``read`` is re-entrant by virtue of it
    being shared, but ``write`` is not). Furthermore, upgrade is permitted from
    read lock to write lock, provided all locks are subsequently released in
    the order they were obtained. In other words, a thread may obtain a read
    lock, then implicitly "upgrade" to a write lock, provided it subsequently
    releases the write lock, then the original read lock.

    .. attribute:: read

        The sub-object providing access to read locks. This object supports the
        context manager protocol, and the typical ``acquire`` and ``release``
        methods (see :meth:`Lock.acquire` and :meth:`Lock.release`).

        The lock obtained via this object is re-entrant and shared (many
        threads may simultaneously share the read lock).

    .. attribute:: write

        The sub-object providing access to write locks. This object supports
        the context manager protocol, and the typical ``acquire`` and
        ``release`` methods (see :meth:`Lock.acquire` and
        :meth:`Lock.release`).

        The lock obtained via this object is re-entrant but exclusive (no other
        thread may hold a read or write lock while this is held). A thread may
        upgrade from a read lock to a write lock, but the lock is *not* held
        continuously during upgrade: the read lock is released before the
        upgraded write lock is obtained. Bear in mind another write lock *may*
        be obtained by another thread before this thread obtains the upgraded
        write lock.
    """

    def __init__(self):
        local = threading.local()
        block_writers = threading.Lock()
        block_readers = threading.Lock()
        read_switch = LightSwitch(block_writers)
        self.read = _ReadLock(local, read_switch, block_readers)
        self.write = _WriteLock(local, read_switch, block_readers, block_writers)


class _BaseLock:
    def __init__(self, local):
        self._local = local

    def _get_state(self):
        # Retrieve the thread-local RWLockState instance. NOTE: Because this
        # is thread-local we never need to worry about locking it (the instance
        # will be specific to the executing thread and no other thread can
        # modify it)
        try:
            state = self._local.state
        except AttributeError:
            state = self._local.state = RWLockState()
        return state


class _ReadLock(_BaseLock):
    def __init__(self, local, read_switch, block_readers):
        super().__init__(local)
        self._read_switch = read_switch
        self._block_readers = block_readers

    def acquire(self, blocking=True, timeout=-1):
        start = monotonic()
        state = self._get_state()
        if state.write > 0:
            # If this thread already holds a write lock (through upgrade or
            # original acquisition), ignore (but count) the read acquisition
            state.ignored += 1
            return True
        if state.read > 0:
            # If the thread already holds only read locks, ignore (but count)
            # the re-entrant attempt. NOTE: This is required to avoid deadlock
            # when a pending write acquisition is holding _block_readers (to
            # avoid starvation -- see below) but a pre-existing read needs to
            # acquire more read locks to complete its processing and ultimately
            # release its original lock
            state.read += 1
            return True
        # NOTE: The block_readers lock *appears* pointless, but blocks the
        # read lock acquisition when a writer holds it (see _WriteLock.acquire)
        # to prevent writer starvation
        if not self._block_readers.acquire(blocking, timeout):
            return False
        self._block_readers.release()
        if not self._read_switch.acquire(blocking, remaining(timeout, start)):
            return False
        state.read = 1
        return True

    def release(self):
        state = self._get_state()
        if state.write > 0:
            assert state.ignored > 0, 'released read before releasing write'
            state.ignored -= 1
            return
        assert state.read > 0, 'released read too many times'
        state.read -= 1
        if state.read > 0:
            return
        self._read_switch.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


class _WriteLock(_BaseLock):
    def __init__(self, local, read_switch, block_readers, block_writers):
        super().__init__(local)
        self._read_switch = read_switch
        self._block_readers = block_readers
        self._block_writers = block_writers

    def acquire(self, blocking=True, timeout=-1):
        start = monotonic()
        state = self._get_state()
        if state.write > 0:
            # Ignore (but count) re-entrant write attempts
            state.write += 1
            return True
        if state.read > 0:
            # A reader wishes to upgrade to a write lock; (temporarily) release
            # its hold on _read_switch and begin the wait for a write lock. If
            # the write lock fails, we *must* re-acquire _read_switch before
            # returning.
            # NOTE: _ReadLock.release is not called here because we want to
            # preserve the thread's state counts
            assert state.ignored == 0, 'double upgrade'
            self._read_switch.release()
        # NOTE: The read_switch acquires block_writers. Hence, when 1 or more
        # readers have acquired read_switch, block_writers is acquired also
        if not self._block_readers.acquire(blocking, remaining(timeout, start)):
            if state.read > 0:
                self._read_switch.acquire()
            return False
        if not self._block_writers.acquire(blocking, remaining(timeout, start)):
            self._block_readers.release()
            if state.read > 0:
                self._read_switch.acquire()
            return False
        state.write = 1
        return True

    def release(self):
        state = self._get_state()
        assert state.write > 0, 'released write too many times'
        state.write -= 1
        if state.write > 0:
            return
        if state.read > 0:
            # A reader that upgraded to a writer is now downgrading back to
            # reader. In this case we "hack" the _read_switch to indicate we're
            # still holding it. We can't acquire it "normally" by calling
            # LightSwitch.acquire as we already hold _block_writers (which is
            # not re-entrant), so we hack the internal count to 1 but maintain
            # our hold on _block_writers.
            #
            # NOTE: the read switch count is the number of *distinct threads*
            # that hold the read switch (which must be 1 in the case of a
            # downgraded writer), *not* the number of re-entrant read locks
            # this thread held before upgrade
            assert state.ignored == 0, 'released write before releasing read'
            with self._read_switch._mutex:
                assert self._read_switch._counter == 0, (
                    'upgraders and readers co-existing')
                self._read_switch._counter = 1
            self._block_readers.release()
            return
        self._block_readers.release()
        self._block_writers.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
