from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


if os.name != "nt":  # pragma: no cover - imported only by the Windows adapter.
    raise RuntimeError("Windows secure files are only available on Windows")


_GENERIC_READ = 0x80000000
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_FILE_TYPE_DISK = 0x0001
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_SYNCHRONIZE = 0x00100000
_OBJ_CASE_INSENSITIVE = 0x00000040
_FILE_OPEN = 0x00000001
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_SEQUENTIAL_ONLY = 0x00000004
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_INVALID_FILENAME_CHARACTERS = frozenset('<>:"|?*')
_RESERVED_BASENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    ]


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.ULONG),
        ("root_directory", wintypes.HANDLE),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", wintypes.LPVOID),
        ("security_quality_of_service", wintypes.LPVOID),
    ]


class _IoStatusValue(ctypes.Union):
    _fields_ = [("status", ctypes.c_long), ("pointer", wintypes.LPVOID)]


class _IoStatusBlock(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("value", _IoStatusValue), ("information", ctypes.c_size_t)]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_create_file = _kernel32.CreateFileW
_create_file.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_create_file.restype = wintypes.HANDLE

_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = (wintypes.HANDLE,)
_close_handle.restype = wintypes.BOOL

_get_file_information = _kernel32.GetFileInformationByHandleEx
_get_file_information.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_get_file_information.restype = wintypes.BOOL

_get_file_size = _kernel32.GetFileSizeEx
_get_file_size.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
_get_file_size.restype = wintypes.BOOL

_get_file_type = _kernel32.GetFileType
_get_file_type.argtypes = (wintypes.HANDLE,)
_get_file_type.restype = wintypes.DWORD

_read_file = _kernel32.ReadFile
_read_file.argtypes = (
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
)
_read_file.restype = wintypes.BOOL

_ntdll = ctypes.WinDLL("ntdll")
_nt_create_file = _ntdll.NtCreateFile
_nt_create_file.argtypes = (
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    ctypes.POINTER(_ObjectAttributes),
    ctypes.POINTER(_IoStatusBlock),
    ctypes.POINTER(ctypes.c_longlong),
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_nt_create_file.restype = ctypes.c_long

_nt_status_to_dos_error = _ntdll.RtlNtStatusToDosError
_nt_status_to_dos_error.argtypes = (wintypes.ULONG,)
_nt_status_to_dos_error.restype = wintypes.ULONG


def _extended_path(path: Path) -> str:
    absolute = os.path.abspath(os.fspath(path))
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _validate_component(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or name[-1] in {" ", "."}
        or any(ord(character) < 32 for character in name)
        or any(character in _INVALID_FILENAME_CHARACTERS for character in name)
        or name.split(".", 1)[0].upper() in _RESERVED_BASENAMES
    ):
        raise ValueError(f"unsafe Windows path component: {name!r}")


def _last_error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


def _open_handle(path: Path, *, directory: bool) -> int:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    desired_access = _GENERIC_READ
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
        desired_access = _FILE_READ_ATTRIBUTES
    else:
        flags |= _FILE_FLAG_SEQUENTIAL_SCAN
    handle = _create_file(
        _extended_path(path),
        desired_access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _last_error()
    return int(handle)


def _open_relative_handle(parent: int, name: str, *, directory: bool) -> int:
    name_buffer = ctypes.create_unicode_buffer(name)
    name_length = len(name.encode("utf-16-le"))
    object_name = _UnicodeString(
        length=name_length,
        maximum_length=name_length + 2,
        buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        length=ctypes.sizeof(_ObjectAttributes),
        root_directory=parent,
        object_name=ctypes.pointer(object_name),
        attributes=_OBJ_CASE_INSENSITIVE,
        security_descriptor=None,
        security_quality_of_service=None,
    )
    status_block = _IoStatusBlock()
    handle = wintypes.HANDLE()
    desired_access = _GENERIC_READ | _SYNCHRONIZE
    create_options = _FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT
    if directory:
        desired_access = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
        create_options |= _FILE_DIRECTORY_FILE
    else:
        create_options |= _FILE_NON_DIRECTORY_FILE | _FILE_SEQUENTIAL_ONLY
    status = _nt_create_file(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        0,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        _FILE_OPEN,
        create_options,
        None,
        0,
    )
    if status < 0:
        error_code = int(_nt_status_to_dos_error(status & 0xFFFFFFFF))
        raise OSError(error_code, ctypes.FormatError(error_code), name)
    if handle.value is None:
        raise OSError("NtCreateFile returned an empty handle")
    return int(handle.value)


def _attributes(handle: int) -> int:
    information = _FileAttributeTagInfo()
    if not _get_file_information(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise _last_error()
    return int(information.file_attributes)


def _close(handle: int) -> None:
    _close_handle(handle)


class WindowsSecureDirectory:
    """A held Windows directory handle that rejects every reparse point."""

    def __init__(self, path: Path, handle: int) -> None:
        self.path = path
        self._handle: int | None = handle

    @classmethod
    def open_root(cls, root: str | Path) -> WindowsSecureDirectory:
        path = Path(os.path.abspath(os.fspath(root)))
        try:
            handle = _open_handle(path, directory=True)
        except OSError as exc:
            raise ValueError(f"cannot open skill root: {path}") from exc
        try:
            attributes = _attributes(handle)
        except OSError as exc:
            _close(handle)
            raise ValueError(f"cannot inspect skill root: {path}") from exc
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            _close(handle)
            raise ValueError("skill root must not be a symlink or reparse point")
        if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
            _close(handle)
            raise ValueError(f"skill root must be a directory: {path}")
        return cls(path, handle)

    def close(self) -> None:
        handle = self._handle
        if handle is not None:
            self._handle = None
            _close(handle)

    def list_entries(self) -> tuple[str, ...]:
        self._require_open()
        try:
            with os.scandir(_extended_path(self.path)) as entries:
                return tuple(sorted(entry.name for entry in entries))
        except OSError as exc:
            raise ValueError(f"cannot list skill root: {self.path}") from exc

    def open_child_directory(
        self,
        name: str,
        *,
        label: str,
        display_path: Path,
        optional: bool = False,
    ) -> WindowsSecureDirectory | None:
        self._require_open()
        try:
            _validate_component(name)
        except ValueError as exc:
            raise ValueError(f"invalid {label} path: {display_path}") from exc
        path = self.path / name
        try:
            handle = _open_relative_handle(self._require_open(), name, directory=True)
        except OSError as exc:
            raise ValueError(f"cannot open {label}: {display_path}") from exc
        try:
            attributes = _attributes(handle)
        except OSError as exc:
            _close(handle)
            raise ValueError(f"cannot inspect {label}: {display_path}") from exc
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            _close(handle)
            raise ValueError(
                f"symlinks are not allowed (including Windows reparse points) "
                f"for {label}: {display_path}"
            )
        if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
            _close(handle)
            if optional:
                return None
            raise ValueError(f"{label} must be a directory: {display_path}")
        return type(self)(path, handle)

    def read_regular_file(
        self,
        relative: str,
        *,
        max_bytes: int,
        label: str,
        display_path: Path,
    ) -> bytes:
        parts = relative.split("/")
        current = self
        opened_directories: list[WindowsSecureDirectory] = []
        try:
            for part in parts[:-1]:
                child = current.open_child_directory(
                    part,
                    label=label,
                    display_path=current.path / part,
                )
                if child is None:  # The non-optional call cannot return None.
                    raise AssertionError("required directory was not opened")
                opened_directories.append(child)
                current = child
            return current._read_child_file(
                parts[-1],
                max_bytes=max_bytes,
                label=label,
                display_path=display_path,
            )
        finally:
            for directory in reversed(opened_directories):
                directory.close()

    def _read_child_file(
        self,
        name: str,
        *,
        max_bytes: int,
        label: str,
        display_path: Path,
    ) -> bytes:
        self._require_open()
        try:
            _validate_component(name)
        except ValueError as exc:
            raise ValueError(f"invalid {label} path: {display_path}") from exc
        try:
            handle = _open_relative_handle(self._require_open(), name, directory=False)
        except OSError as exc:
            raise ValueError(f"cannot open {label}: {display_path}") from exc
        try:
            try:
                attributes = _attributes(handle)
            except OSError as exc:
                raise ValueError(f"cannot inspect {label}: {display_path}") from exc
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(
                    f"symlinks are not allowed (including Windows reparse points) "
                    f"for {label}: {display_path}"
                )
            if (
                attributes & _FILE_ATTRIBUTE_DIRECTORY
                or _get_file_type(handle) != _FILE_TYPE_DISK
            ):
                raise ValueError(f"{label} must be a regular file: {display_path}")

            size = ctypes.c_longlong()
            if not _get_file_size(handle, ctypes.byref(size)):
                raise ValueError(
                    f"cannot inspect {label}: {display_path}"
                ) from _last_error()
            if size.value > max_bytes:
                raise ValueError(f"{label} exceeds {max_bytes} bytes: {display_path}")

            chunks: list[bytes] = []
            total = 0
            while total <= max_bytes:
                capacity = min(65_536, max_bytes + 1 - total)
                buffer = ctypes.create_string_buffer(capacity)
                read = wintypes.DWORD()
                if not _read_file(handle, buffer, capacity, ctypes.byref(read), None):
                    raise ValueError(
                        f"cannot read {label}: {display_path}"
                    ) from _last_error()
                if read.value == 0:
                    break
                chunks.append(buffer.raw[: read.value])
                total += read.value
            if total > max_bytes:
                raise ValueError(f"{label} exceeds {max_bytes} bytes: {display_path}")
            data = b"".join(chunks)
            if b"\x00" in data:
                raise ValueError(
                    f"NUL bytes are not allowed in {label}: {display_path}"
                )
            return data
        finally:
            _close(handle)

    def _require_open(self) -> int:
        if self._handle is None:
            raise RuntimeError("Windows secure directory is closed")
        return self._handle
