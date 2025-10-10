from time import sleep
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

    threads = [Thread(target=enter_room) for i in range(5)]
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


def test_lightswitch_mutex_blocked():
    light = Lock()
    switch = LightSwitch(light)
    results = []

    def try_acquire():
        results.append(switch.acquire(blocking=False))

    with light:
        # We've acquire the "light" lock so the lightswitch can't acquire it
        threads = [Thread(target=try_acquire) for i in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
    print(results)
    assert all(not acquired for acquired in results)


#def test_lock_acquire_release():
#    lock = RWLock()
#    # Test that we can repeatedly lock and unlock with write after write, read
#    # after write, and write after read
#    with lock.read:
#        assert True
#    with lock.write:
#        assert True
#    with lock.write:
#        assert True
#    with lock.read:
#        assert True
#
#
#def test_read_lock_reentrant():
#    lock = RWLock()
#    with lock.read:
#        with lock.read:
#            with lock.read:
#                assert True
#
#
#def test_read_lock_concurrent():
#    evt = Event()
#    lock = RWLock()
#    def get_read():
#        with lock.read:
#            evt.wait()
#    thread1 = Thread(target=get_read)
#    thread1.start()
#    thread2 = Thread(target=get_read)
#    thread2.start()
#    with lock.read:
#        evt.set()
#    thread2.join(timeout=1)
#    thread1.join(timeout=1)
