"""Bluetooth helpers shared by the modules."""

from __future__ import annotations


def allow_duplicates(scanner) -> bool:
    """On macOS, ask CoreBluetooth for every broadcast instead of only the first one per scan.

    `scanner` is a running BleakScanner or a bleak platform scanner backend. bleak (3.0.2) has
    no option for this, so repeat the scan call it just made, with
    CBCentralManagerScanOptionAllowDuplicatesKey set; CoreBluetooth then replaces the running
    scan's options. Returns False on other platforms, or if bleak's internals have moved.
    """
    backend = getattr(scanner, "_backend", scanner)
    try:
        from CoreBluetooth import CBCentralManagerScanOptionAllowDuplicatesKey

        central_manager = backend._manager.central_manager
    except (ImportError, AttributeError):
        return False
    central_manager.scanForPeripheralsWithServices_options_(None, {CBCentralManagerScanOptionAllowDuplicatesKey: True})
    return True
