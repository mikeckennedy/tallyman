"""Shared fixtures."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

FIFO_UNBLOCK_AFTER = 2.0  # seconds before a blocked reader or writer of a test FIFO is released


@pytest.fixture
def make_fifo() -> Iterator[Callable[..., Path]]:
    """Create a FIFO. If anything blocks opening it, it is unblocked after 2 s, so a regression fails its
    assertion instead of hanging the suite: a blocked reader by a writer sending *payload*, or, with
    *for_writer*, a blocked writer by a reader that drains it until the test ends.

    Call it as ``make_fifo(path, payload=b'', for_writer=False)``. Tests that use it must skip where
    ``os.mkfifo`` is missing.
    """
    stop = threading.Event()
    threads: list[threading.Thread] = []
    fifos: list[Path] = []

    def unblock(path: Path, payload: bytes) -> None:
        if stop.wait(FIFO_UNBLOCK_AFTER):
            return
        # Opening for writing without blocking succeeds only once a reader is waiting (ENXIO otherwise),
        # so keep trying until the test ends, serving every reader: code that opens the FIFO twice
        # (a binary check, then the counter) must not hang on the second open
        while not stop.is_set():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                stop.wait(0.05)
                continue
            try:
                os.write(fd, payload)
            except OSError:
                pass  # the reader went away first
            finally:
                os.close(fd)
            stop.wait(0.05)

    def drain(path: Path) -> None:
        if stop.wait(FIFO_UNBLOCK_AFTER):
            return
        # Opening for reading without blocking always succeeds; while this end is open, a writer's open
        # completes and its writes land here instead of failing with a broken pipe
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            while not stop.is_set():
                try:
                    os.read(fd, 65536)
                except BlockingIOError:
                    pass
                stop.wait(0.05)
        finally:
            os.close(fd)

    def make(path: Path, payload: bytes = b'', for_writer: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        fifos.append(path)
        if for_writer:
            thread = threading.Thread(target=drain, args=(path,), daemon=True)
        else:
            thread = threading.Thread(target=unblock, args=(path, payload), daemon=True)
        thread.start()
        threads.append(thread)
        return path

    yield make

    stop.set()
    for thread in threads:
        thread.join(timeout=1.0)
    for fifo in fifos:
        fifo.unlink(missing_ok=True)  # nothing left behind can block a later scan of the same tree
