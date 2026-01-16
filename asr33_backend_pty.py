#!/usr/bin/env python3

"""
PTY backend for ASR-33 emulator.

Spawns a shell (/bin/sh) in a pseudo-terminal and connects it to the emulator.
Uses /bin/sh for cleaner behavior on dumb terminals - modern shells like zsh
and bash have features (fancy prompts, escape sequences) that don't work well
on teletypes.

Note: This backend only works on Unix-like systems (Linux, macOS).
      The pty module is not available on Windows.
"""

import os
import sys
import select
import threading
import queue
from typing import Any

# pty/termios modules are Unix-only
if sys.platform != "win32":
    import pty
    import termios
    import struct
    import fcntl
else:
    pty = None  # type: ignore
    termios = None  # type: ignore
    struct = None  # type: ignore
    fcntl = None  # type: ignore


class PtyBackend:
    """PTY backend that spawns a shell for the ASR-33 emulator."""

    def __init__(
        self,
        upper_layer: Any = None,
        config: Any = None,
        send_queue_size: int = 8
    ):
        """
        Initialize PTY backend.

        Args:
            upper_layer: Layer to send received data to.
            config: Configuration (unused, for interface compatibility).
            send_queue_size: Size of the send queue.
        """
        self.upper_layer = upper_layer
        self._send_queue: queue.Queue[bytes] = queue.Queue(send_queue_size)
        self._running = False
        self._master_fd: int | None = None
        self._pid: int | None = None
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None

        # Use /bin/sh by default for cleaner TTY behavior
        # Modern shells (zsh, bash) have features that don't work well on dumb terminals
        self._shell = "/bin/sh"

    def start(self) -> None:
        """Start the PTY and shell process."""
        if self._running:
            return

        if pty is None:
            raise RuntimeError("PTY backend is not available on Windows")

        # Fork a new process with a PTY
        self._pid, self._master_fd = pty.fork()

        if self._pid == 0:
            # Child process - exec the shell
            # Set TERM to something basic that works with teletypes
            os.environ["TERM"] = "dumb"
            # Simple prompt for bash (zsh ignores PS1 in favor of PROMPT)
            os.environ["PS1"] = "$ "
            os.environ["PROMPT"] = "$ "
            # Disable common shell features that don't work on dumb terminals
            os.environ["HISTFILE"] = ""  # Don't save history
            os.execlp(self._shell, self._shell)
            # If exec fails, exit
            os._exit(1)

        # Parent process - configure PTY
        # Set PTY size to match ASR-33 (72 columns typical)
        if termios is not None and struct is not None and fcntl is not None:
            try:
                # TIOCSWINSZ sets window size: rows, cols, xpixel, ypixel
                winsize = struct.pack('HHHH', 24, 72, 0, 0)
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
            except (OSError, AttributeError):
                pass  # Non-fatal if we can't set size

        # Set up threads to handle I/O
        self._running = True
        self._rx_thread = threading.Thread(target=self._pty_rx_worker, daemon=True)
        self._tx_thread = threading.Thread(target=self._pty_tx_worker, daemon=True)
        self._rx_thread.start()
        self._tx_thread.start()

    def _pty_rx_worker(self) -> None:
        """Background thread: read from PTY and send to upper layer."""
        while self._running and self._master_fd is not None:
            try:
                # Use select to wait for data with timeout
                readable, _, _ = select.select([self._master_fd], [], [], 0.1)
                if readable:
                    data = os.read(self._master_fd, 1024)
                    if data:
                        if self.upper_layer and hasattr(self.upper_layer, 'receive_data'):
                            self.upper_layer.receive_data(data)
                    else:
                        # EOF - shell exited
                        self._running = False
                        break
            except OSError:
                # PTY closed
                self._running = False
                break

    def _pty_tx_worker(self) -> None:
        """Background thread: write to PTY from send queue."""
        while self._running and self._master_fd is not None:
            try:
                data = self._send_queue.get(timeout=0.1)
                if data and self._master_fd is not None:
                    os.write(self._master_fd, data)
            except queue.Empty:
                continue
            except OSError:
                # PTY closed
                self._running = False
                break

    def send_data(self, data: bytes) -> None:
        """Queue data to be sent to the PTY."""
        if data and self._running:
            self._send_queue.put(data)

    def receive_data(self, data: bytes) -> None:
        """Not used - data comes from PTY via rx thread."""
        pass

    def get_info_string(self) -> str:
        """Return info string."""
        return f"pty:{self._shell}"

    def close(self) -> None:
        """Close the PTY and stop threads."""
        self._running = False

        # Close the master PTY fd
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

        # Wait for threads to finish
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=1.0)
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=1.0)

        # Terminate the child process if still running
        if self._pid is not None and self._pid > 0:
            try:
                os.kill(self._pid, 9)
                os.waitpid(self._pid, 0)
            except (OSError, ChildProcessError):
                pass
            self._pid = None
