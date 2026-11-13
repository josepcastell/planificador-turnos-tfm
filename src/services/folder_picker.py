"""Finestra de Windows per triar una carpeta (la de l'Explorador,
«Selecciona una carpeta»).

Només amb ctypes: el Python portable és l'«embeddable» i no porta tkinter.
Fa servir el diàleg modern IFileOpenDialog (FOS_PICKFOLDERS) en un fil
propi amb COM en mode STA, perquè no depengui de l'estat COM del fil de
Streamlit. El servidor corre al mateix ordinador i sessió que l'usuari,
així que la finestra li surt a la pantalla."""
from __future__ import annotations

import sys
import threading


class FolderPickerUnavailable(RuntimeError):
    """No s'ha pogut obrir la finestra (no és Windows o ha fallat COM)."""


_CLSID_FILE_OPEN_DIALOG = "{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}"
_IID_IFILE_OPEN_DIALOG = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
_IID_ISHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
_FOS_PICKFOLDERS = 0x20
_FOS_FORCEFILESYSTEM = 0x40
_FOS_PATHMUSTEXIST = 0x800
_SIGDN_FILESYSPATH = 0x80058000 - (1 << 32)  # com a enter amb signe (c_int)
_ERROR_CANCELLED = 0x800704C7 - (1 << 32)
# Posicions a la vtable (IUnknown 0-2, IModalWindow 3, IFileDialog 4-26).
_SHOW, _SET_OPTIONS, _GET_OPTIONS, _SET_FOLDER = 3, 9, 10, 12
_SET_TITLE, _GET_RESULT, _RELEASE = 17, 20, 2
_GET_DISPLAY_NAME = 5  # IShellItem


def _dialog(initial: str | None, title: str, owner: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                    ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.WinDLL("ole32")  # HRESULT comprovat a mà (check)
    shell32 = ctypes.WinDLL("shell32")

    def guid(text: str) -> GUID:
        g = GUID()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    def method(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        fn = proto(vtbl[index])
        return lambda *args: fn(obj, *args)

    def check(hr: int, what: str) -> None:
        if hr < 0:
            raise FolderPickerUnavailable(f"{what}: 0x{hr & 0xFFFFFFFF:08X}")

    ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    try:
        dialog = ctypes.c_void_p()
        check(ole32.CoCreateInstance(
            ctypes.byref(guid(_CLSID_FILE_OPEN_DIALOG)), None, 1,  # INPROC
            ctypes.byref(guid(_IID_IFILE_OPEN_DIALOG)), ctypes.byref(dialog),
        ), "CoCreateInstance")
        try:
            opts = wintypes.DWORD()
            check(method(dialog, _GET_OPTIONS, ctypes.POINTER(wintypes.DWORD))(
                ctypes.byref(opts)), "GetOptions")
            check(method(dialog, _SET_OPTIONS, wintypes.DWORD)(
                opts.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST,
            ), "SetOptions")
            method(dialog, _SET_TITLE, ctypes.c_wchar_p)(title)
            if initial:
                folder = ctypes.c_void_p()
                hr = shell32.SHCreateItemFromParsingName(
                    ctypes.c_wchar_p(initial), None,
                    ctypes.byref(guid(_IID_ISHELL_ITEM)), ctypes.byref(folder),
                )
                if hr >= 0 and folder:
                    method(dialog, _SET_FOLDER, ctypes.c_void_p)(folder)
                    method(folder, _RELEASE)()
            hr = method(dialog, _SHOW, wintypes.HWND)(owner or None)
            if hr == _ERROR_CANCELLED:
                return None
            check(hr, "Show")
            item = ctypes.c_void_p()
            check(method(dialog, _GET_RESULT, ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(item)), "GetResult")
            try:
                path = ctypes.c_wchar_p()
                check(method(item, _GET_DISPLAY_NAME, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_wchar_p))(
                    _SIGDN_FILESYSPATH, ctypes.byref(path)), "GetDisplayName")
                result = path.value
                ole32.CoTaskMemFree(path)
                return result
            finally:
                method(item, _RELEASE)()
        finally:
            method(dialog, _RELEASE)()
    finally:
        ole32.CoUninitialize()


def pick_folder(initial: str | None = None, title: str = "Tria una carpeta") -> str | None:
    """Obre la finestra de Windows per triar una carpeta i la retorna, o
    None si l'usuari cancel·la. Llança FolderPickerUnavailable si la
    finestra no es pot obrir (llavors la interfície deixa escriure la
    ruta a mà)."""
    if sys.platform != "win32":
        raise FolderPickerUnavailable("només a Windows")
    import ctypes
    # Propietària = la finestra que l'usuari té al davant (el navegador on
    # acaba de clicar): així el diàleg li surt al damunt i no amagat.
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = user32.GetForegroundWindow()
    box: dict = {}

    def run() -> None:
        try:
            box["path"] = _dialog(initial, title, owner)
        except Exception as exc:  # noqa: BLE001 — qualsevol error = no disponible
            box["error"] = exc

    worker = threading.Thread(target=run, name="folder-picker", daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        err = box["error"]
        raise err if isinstance(err, FolderPickerUnavailable) else FolderPickerUnavailable(str(err))
    return box.get("path")
