#!/usr/bin/env python3

"""
Serial port backend for ASR-33 emulator.

- Uses pyserial for COM/tty access.
- Reader thread enqueues incomming_queue data.
- Main thread calls pump() to feed terminal safely.
- Configurable port, baudrate, bytesize, parity, stopbits.
"""

import sys
import threading
import time
import queue
from typing import Any
import serial

class SerialBackend:
    """Serial port backend for ASR-33 emulator."""
    def __init__(
        self,
        upper_layer : Any,
        config,
        send_queue_size: int = 8  # keep tape reader from running too far ahead
    ):
        """
        Initialize serial backend.

        Args:
            terminal: Terminal instance to feed data into.
            port: COM port or device path (e.g. "COM3" or "/dev/ttyUSB0").
            baudrate: Baud rate (e.g. 110 for ASR-33, 9600 for modern).
            bytesize: Number of data bits (serial.FIVEBITS, SIXBITS, SEVENBITS, EIGHTBITS).
            parity: Parity (serial.PARITY_NONE, PARITY_EVEN, PARITY_ODD, PARITY_MARK, PARITY_SPACE).
            stopbits: Stop bits (serial.STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO).
            timeout: Read timeout in seconds.
        """
        self.upper_layer = upper_layer
        self.ser = serial.Serial(
            port=config.get("port", default="COM4"),
            baudrate=config.get("baudrate", default=9600),
            bytesize=config.get("databits", default=serial.EIGHTBITS),
            parity=config.get("parity", default=serial.PARITY_NONE),
            stopbits=config.get("stopbits", default=serial.STOPBITS_ONE),
            timeout=0
        )
        # set_buffer_size is not supported by pyserial on Linux
        if sys.platform.startswith("win"):
            self.ser.set_buffer_size(rx_size=8, tx_size=4096)
        self._send_queue = queue.Queue(send_queue_size)

        self._running = True
        self._rx_thread = threading.Thread(target=self._serial_rx_worker, daemon=True)
        self._tx_thread = threading.Thread(target=self._serial_tx_worker, daemon=True)

        self._rx_thread.start()
        self._tx_thread.start()

    def _serial_rx_worker(self) -> None:
        """Background thread: read from serial port and send to upper layer."""
        while self._running:
            # At startup, upper_layer may not be set yet
            if self.ser.in_waiting:
                if self.upper_layer is None or not hasattr(self.upper_layer, 'receive_data'):
                    time.sleep(0.100)
                    continue
                data = self.ser.read(self.ser.in_waiting)
                if data:
                    self.upper_layer.receive_data(data)
                    time.sleep(0.005)  # smaller delay when data is received
                    continue
            time.sleep(0.050)  # Larger delay when idle

    def _serial_tx_worker(self) -> None:
        """Background thread: write to serial port from send queue."""
        while self._running:
            if not self._send_queue.empty():
                data = self._send_queue.get()
                self.ser.write(data)
                time.sleep(0.005)  # smaller delay after sending data
                continue
            time.sleep(0.050)  # Larger delay when idle

    def send_data(self, data: bytes) -> None:
        """Queues data received from upper layer to be sent to the lower layer."""
        if data:
            self._send_queue.put(data)

    def get_info_string(self) -> str:
        """Return a string with information about the serial port."""
        return (
            f"{self.ser.port}:{self.ser.baudrate}-"
            f"{self.ser.bytesize}{self.ser.parity}{self.ser.stopbits}"
        )

    def close(self) -> None:
        """Close the serial port and stop the backend thread."""
        self._running = False
        self._tx_thread.join()
        self._rx_thread.join()
        if self.ser.is_open:
            self.ser.close()
