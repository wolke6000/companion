from ctypes import *
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent  # directory containing host.py
# Allow Windows to resolve dependent DLLs from this folder too (Python 3.8+)
os.add_dll_directory(str(HERE))
dll_path = HERE / "swinput.dll"
dll = CDLL(str(dll_path))

SWINPUT_OK = 0
SWINPUT_ERR = 1
SWINPUT_ERR_INVALID_ARG = 2
SWINPUT_ERR_NOT_RUNNING = 3
SWINPUT_ERR_BUFFER_TOO_SMALL = 4
SWINPUT_ERR_DEVICE_NOT_FOUND = 5
SWINPUT_ERR_UNKNOWN_DEVICE = 6
SWINPUT_ERR_DECODING_FAILED = 7
SWINPUT_COM_NOT_FOUND = 8
SWINPUT_ERR_WINAPI_FAILED = 1000

class SWINPUT_Stats(Structure):
    _fields_ = [
        ("reports_written", c_uint64),
        ("ring_overflows", c_uint64),
        ("rawinput_errors", c_uint64),
        ("devices_known", c_uint32),
        ("ring_bytes_capacity", c_uint32),
        ("ring_bytes_used_approx", c_uint32),
    ]

class SWINPUT_DeviceInfo(Structure):
    _fields_ = [
        ("device_hash", c_uint64),
        ("type", c_uint16),
        ("vid", c_uint16),
        ("pid", c_uint16),
        ("usage_page", c_uint16),
        ("usage", c_uint16),
        ("hid_path", c_wchar * 512),
        ("product_name", c_wchar * 512),
        ("serial_number", c_wchar * 512),
        ("manufacturer", c_wchar * 512),
        ("button_count", c_uint16),
        ("axes_present", c_uint16),
        ("axes_logical_min", c_int32 * 16),
        ("axes_logical_max", c_int32 * 16)
    ]

class SWINPUT_DecodedReport(Structure):
    _fields_ = [
        ("device_hash", c_uint64),
        ("qpc", c_uint64),
        ("button_count", c_uint32),
        ("buttons", c_uint32 * 8),
        ("axis", c_int32 * 9),
        ("axis_present", c_uint16)
    ]

class SWINPUT_CaptureParams(Structure):
    _fields_ = [
        ("ring_buffer_size_bytes", c_uint32),
        ("keyframe_interval_ms", c_uint32),
        ("flags", c_uint32)
    ]

dll.swinput_start_capture.argtypes = [POINTER(SWINPUT_CaptureParams)]
dll.swinput_start_capture.restype  = c_uint8

dll.swinput_stop_capture.argtypes = []
dll.swinput_stop_capture.restype  = None

dll.swinput_get_stats.argtypes = [POINTER(SWINPUT_Stats)]
dll.swinput_get_stats.restype  = c_uint8

dll.swinput_enum_devices.argtypes = [POINTER(SWINPUT_DeviceInfo), POINTER(c_uint32)]
dll.swinput_enum_devices.restype  = c_uint8

dll.swinput_read_reports.argtypes = [POINTER(c_uint8), c_uint32, c_uint32, POINTER(c_uint32)]
dll.swinput_read_reports.restype  = c_uint8

dll.swinput_decode_report.argtypes = [POINTER(c_uint8), POINTER(SWINPUT_DecodedReport)]
dll.swinput_decode_report.restype  = c_uint8

dll.swinput_get_com_port.argtypes = [c_uint64, POINTER(c_wchar)]
dll.swinput_decode_report.restype  = c_uint8

axis_names = [
    "X",
    "Y",
    "Z",
    "Rx",
    "Ry",     
    "Rz",
    "Slider",
    "Dial",
    "Wheel"
]

def enumerate_devices():
    for attempt in range(2):
        required = c_uint32(0)

        # Pass 1: query required count
        rc = dll.swinput_enum_devices(None, byref(required))
        if rc != SWINPUT_OK:
            raise RuntimeError(f"swinput_enum_devices(count) failed: {rc}")

        n = required.value

        if n == 0:
            return []

        devices_array_type = SWINPUT_DeviceInfo * n
        devices_array = devices_array_type()

        # Pass 2: provide capacity explicitly
        capacity = c_uint32(n)
        rc = dll.swinput_enum_devices(devices_array, byref(capacity))

        if rc == SWINPUT_OK:
            return list(devices_array[:capacity.value])

        if rc == SWINPUT_ERR_BUFFER_TOO_SMALL:
            # device set changed between calls; retry
            continue

        raise RuntimeError(f"swinput_enum_devices(data) failed: {rc}")

    raise RuntimeError("swinput_enum_devices failed: device list unstable (changed repeatedly)")


def start_capture(buffer_size=1024 * 1024, keyframe_interval_ms=1000, flags=1):
    params = SWINPUT_CaptureParams(buffer_size, keyframe_interval_ms, flags)
    result = dll.swinput_start_capture(byref(params))
    if result != 0:
        raise RuntimeError(f"swinput_start_capture failed with error code {result}")


def stop_capture():
    result = dll.swinput_stop_capture()
    if result != 0:
        raise RuntimeError(f"swinput_stop_capture failed with error code {result}")


def get_stats():
    stats = SWINPUT_Stats()
    result = dll.swinput_get_stats(byref(stats))
    if result != 0:
        raise RuntimeError(f"swinput_get_stats failed with error code {result}")
    return stats


def read_reports(max_reports=256):
    buffer_size = max_reports * 64  # assuming max report size is 64 bytes
    buffer = (c_uint8 * buffer_size)()
    reports_read = c_uint32(0)
    
    result = dll.swinput_read_reports(buffer, buffer_size, max_reports, byref(reports_read))
    if result != 0:
        raise RuntimeError(f"swinput_read_reports failed with error code {result}")
    
    off = 0

    while off+4 <= reports_read.value:
        report_size = int.from_bytes(buffer[off:off+4], 'little')
        if off + report_size > reports_read.value:
            break
        rec = (c_uint8 * report_size)(*buffer[off:off+report_size])
        this_report = SWINPUT_DecodedReport()
        dll.swinput_decode_report(rec, byref(this_report))
        off += report_size
        yield this_report

def get_com_port(device_hash):
    comport = create_unicode_buffer(32)
    result = dll.swinput_get_com_port(device_hash, comport)
    if result != 0:
        raise RuntimeError(f"swinput_get_com_port failed with error code {result}")
    return comport.value