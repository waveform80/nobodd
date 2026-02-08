# nobodd: a boot configuration tool for the Raspberry Pi
#
# Copyright (c) 2025-2026 Dave Jones <dave.jones@canonical.com>
# Copyright (c) 2025-2026 Canonical Ltd.
#
# SPDX-License-Identifier: GPL-3.0

from time import sleep, monotonic
from threading import Thread, Event, Lock, get_ident

import pytest

from nobodd.locks import *


@pytest.fixture(params=(False, True))
def blocking(request):
    yield request.param


def test_lightswitch(blocking):
    light = Lock()
    switch = LightSwitch(light)
    leave = Event()
    in_room = set()

    def enter_room():
        switch.acquire(blocking=blocking)
        try:
            in_room.add(get_ident())
            leave.wait()
        finally:
            switch.release()
            in_room.remove(get_ident())

    threads = [Thread(target=enter_room, daemon=True) for i in range(5)]
    for thread in threads:
        thread.start()
    # Wait until all background threads have "entered the room" (turning on
    # the "light")
    while len(in_room) < 5:
        sleep(0.01)
    # Ensure we (in the main thread) can't acquire the "light" lock
    assert not light.acquire(blocking=False)
    # Have all the threads "leave" and wait until they're all "gone"
    leave.set()
    for thread in threads:
        thread.join(timeout=1)
        assert not thread.is_alive()
    assert not in_room
    # Ensure we *can* acquire the "light" lock
    assert light.acquire(blocking=False)


def test_lightswitch_lock_blocked():
    light = Lock()
    switch = LightSwitch(light)
    results = []

    def try_acquire():
        results.append(switch.acquire(blocking=False))

    with light:
        # We've acquired the "light" lock so the lightswitch can't acquire it
        thread = Thread(target=try_acquire, daemon=True)
        thread.start()
        thread.join(timeout=1)
    assert results == [False]


def test_lightswitch_mutex_blocked():
    light = Lock()
    switch = LightSwitch(light)
    results = []

    def try_acquire():
        results.append(switch.acquire(blocking=False))

    with switch._mutex:
        # The light lock is not acquired, but we have blocked the lightswitch's
        # internal mutex for the counter so this should still fail
        thread = Thread(target=try_acquire, daemon=True)
        thread.start()
        thread.join(timeout=1)
    assert results == [False]


def test_lightswitch_not_acquired():
    light = LightSwitch(Lock())
    with pytest.raises(RuntimeError):
        light.release()


def test_lightswitch_context():
    light = LightSwitch(Lock())
    with light:
        assert light._counter == 1
        with light:
            assert light._counter == 2
    assert light._counter == 0


def test_rwlock_acquire_release():
    lock = RWLock()
    # Test that we can repeatedly lock and unlock with write after write, read
    # after write, and write after read
    for i in range(5):
        with lock.read:
            assert True
        with lock.write:
            assert True
        with lock.write:
            assert True
        with lock.read:
            assert True
        with lock.write:
            assert True


def test_rwlock_read_reentrant():
    lock = RWLock()
    with lock.read:
        with lock.read:
            with lock.read:
                assert True


def test_rwlock_write_reentrant():
    lock = RWLock()
    with lock.write:
        with lock.write:
            with lock.write:
                assert True


def test_rwlock_write_upgrade():
    lock = RWLock()
    with lock.read:
        with lock.write:
            with lock.read:
                assert True


def test_rwlock_read_is_shared():
    evt = Event()
    lock = RWLock()
    in_lock = set()
    def get_read():
        with lock.read:
            in_lock.add(get_ident())
            evt.wait()
    threads = [Thread(target=get_read, daemon=True) for i in range(5)]
    for thread in threads:
        thread.start()
    while len(in_lock) < 5:
        sleep(0.01)
    with lock.read:
        evt.set()
    for thread in threads:
        thread.join(timeout=1)
        assert not thread.is_alive()


def test_rwlock_write_is_exclusive():
    lock = RWLock()
    results = []

    def get_write():
        results.append(lock.write.acquire(blocking=False))

    with lock.write:
        writer = Thread(target=get_write, daemon=True)
        writer.start()
        writer.join(timeout=1)
    assert not writer.is_alive()
    assert results == [False]


def test_rwlock_read_nonblocking():
    lock = RWLock()
    results = []

    def get_read():
        results.append(lock.read.acquire(blocking=False))

    with lock.write:
        reader = Thread(target=get_read, daemon=True)
        reader.start()
        reader.join(timeout=1)
    assert not reader.is_alive()
    assert results == [False]


def test_rwlock_read_nonblocking_later():
    lock = RWLock()
    results = []

    def get_read():
        results.append(lock.read.acquire(blocking=False))

    # Take the lock that read_switch would acquire without locking
    # block_readers
    with lock.write._block_writers:
        reader = Thread(target=get_read, daemon=True)
        reader.start()
        reader.join(timeout=1)
    assert not reader.is_alive()
    assert results == [False]


def test_rwlock_read_upgrade_fail():
    got_read = Event()
    get_upgrade = Event()
    get_write = Event()
    lock = RWLock()
    results = []

    def upgrader():
        with lock.read:
            got_read.set()
            get_upgrade.wait()
            results.append(lock.write.acquire(blocking=False))

    def writer():
        get_write.set()
        with lock.write:
            pass

    # Organize execution of threads to guarantee upgrader gets a read lock,
    # writer gets a write lock, then upgrader fails to upgrade because it
    # can't acquire _block_readers
    upgrader_t = Thread(target=upgrader, daemon=True)
    upgrader_t.start()
    got_read.wait()
    writer_t = Thread(target=writer, daemon=True)
    writer_t.start()
    get_write.wait()
    get_upgrade.set()
    upgrader_t.join(timeout=1)
    assert not upgrader_t.is_alive()
    writer_t.join(timeout=1)
    assert not writer_t.is_alive()
    assert results == [False]


@pytest.mark.xfail(reason="flaky test")
def test_rwlock_read_upgrade_fail_on_writer():
    got_read = Event()
    get_upgrade = Event()
    getting_write = Event()
    lock = RWLock()
    results = []

    def upgrader():
        with lock.read:
            got_read.set()
            get_upgrade.wait()
            results.append(lock.write.acquire(blocking=False))
            if results == [True]:
                lock.write.release()

    def writer():
        # The attempted upgrade will release the read_switch, which will
        # release block_writers which we'll be actively waiting on. If we're
        # *lucky* we'll get _block_writers instead of the upgraders thread,
        # but it's a roll of the CPU scheduler that determines this...
        getting_write.set()
        with lock.write._block_writers:
            pass

    # Because we're relying on random chance in the scheduler this is a flaky
    # test and is marked to xfail. It seems very dependent on architecture,
    # interpreter version and so forth. I can usually get this working on a Pi
    # with an older interpreter, but a big PC with a later one is impossible.
    start = monotonic()
    while True:
        upgrader_t = Thread(target=upgrader, daemon=True)
        upgrader_t.start()
        got_read.wait()
        writer_t = Thread(target=writer, daemon=True)
        writer_t.start()
        getting_write.wait()
        get_upgrade.set()
        upgrader_t.join(timeout=1)
        assert not upgrader_t.is_alive()
        writer_t.join(timeout=1)
        assert not writer_t.is_alive()
        if results == [False]:
            break

        # Try again...
        got_read.clear()
        get_upgrade.clear()
        getting_write.clear()
        results.clear()
        if monotonic() - start > 2:
            assert False
