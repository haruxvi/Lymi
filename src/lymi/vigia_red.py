"""Con quien habla lymi de verdad: conexiones de un proceso y de todos sus hijos.

No basta con que el motor web prometa no llamar a casa, ni con su propio registro
de red: WebView2 abre conexiones desde codigo que ese registro no ve. Lo que
cuenta es la tabla de conexiones del sistema operativo, que es lo que se lee aqui:

- Windows: la lista de procesos del sistema y `netstat -ano`.
- Linux: `/proc` (procesos, sockets y sus inodos). Sin root: los procesos propios
  se pueden leer.
- macOS: `ps` y `lsof`, que vienen con el sistema.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Conexion:
    protocolo: str
    remoto: str
    puerto: int
    pid: int

    def __str__(self) -> str:
        return f"{self.protocolo} {self.remoto}:{self.puerto} (pid {self.pid})"


def es_externa(host: str) -> bool:
    """Una direccion fuera de esta maquina. Las sin destino (0.0.0.0, ::) no cuentan."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # lo que no se entiende se reporta, no se esconde
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (ip.is_loopback or ip.is_unspecified)


def _separar(direccion: str) -> tuple[str, int] | None:
    """`1.2.3.4:443`, `[::1]:80` o `1.2.3.4.443` (lsof no) -> (host, puerto). `*:*` -> None."""
    host, _, puerto = direccion.rpartition(":")
    if not host or not puerto.isdigit():
        return None
    return host.strip("[]").split("%")[0], int(puerto)


def _externa(protocolo: str, remoto: tuple[str, int] | None, pid: int) -> Conexion | None:
    if remoto is None or remoto[1] == 0 or not es_externa(remoto[0]):
        return None
    return Conexion(protocolo, remoto[0], remoto[1], pid)


def descendientes(raiz: int, pares: Iterable[tuple[int, int]]) -> set[int]:
    """`raiz` y todos sus descendientes, dado (pid, padre) de cada proceso."""
    hijos: dict[int, list[int]] = {}
    for pid, padre in pares:
        if pid != padre:
            hijos.setdefault(padre, []).append(pid)
    vistos, pendientes = {raiz}, [raiz]
    while pendientes:
        for hijo in hijos.get(pendientes.pop(), []):
            if hijo not in vistos:
                vistos.add(hijo)
                pendientes.append(hijo)
    return vistos


def _ejecutar(*args: str) -> str:
    return subprocess.run(
        list(args), capture_output=True, text=True, errors="replace", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


# ---------------------------------------------------------------- Windows


def leer_netstat(texto: str, pids: Iterable[int]) -> list[Conexion]:
    """Las conexiones externas de esos procesos en la salida de `netstat -ano`."""
    buscados = set(pids)
    halladas: list[Conexion] = []
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) < 4 or partes[0] not in {"TCP", "UDP"} or not partes[-1].isdigit():
            continue
        pid = int(partes[-1])
        if pid in buscados and (c := _externa(partes[0], _separar(partes[2]), pid)):
            halladas.append(c)
    return halladas


def _procesos_windows() -> list[tuple[int, int]]:
    import ctypes
    from ctypes import wintypes

    class Entrada(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    foto = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if foto in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "no se pudo listar los procesos")
    pares: list[tuple[int, int]] = []
    try:
        entrada = Entrada()
        entrada.dwSize = ctypes.sizeof(Entrada)
        ok = k32.Process32FirstW(foto, ctypes.byref(entrada))
        while ok:
            pares.append((entrada.th32ProcessID, entrada.th32ParentProcessID))
            ok = k32.Process32NextW(foto, ctypes.byref(entrada))
    finally:
        k32.CloseHandle(foto)
    return pares


# ---------------------------------------------------------------- Linux


def direccion_proc(hexadecimal: str) -> tuple[str, int]:
    """`0100007F:1F90` de /proc/net/tcp -> ('127.0.0.1', 8080). Palabras en orden del host."""
    ip_hex, puerto_hex = hexadecimal.split(":")
    crudo = bytes.fromhex(ip_hex)
    if sys.byteorder == "little":
        crudo = b"".join(crudo[i : i + 4][::-1] for i in range(0, len(crudo), 4))
    familia = socket.AF_INET if len(crudo) == 4 else socket.AF_INET6
    return socket.inet_ntop(familia, crudo), int(puerto_hex, 16)


def leer_proc_net(texto: str, protocolo: str) -> dict[int, tuple[str, int]]:
    """inodo -> direccion remota, de un /proc/net/{tcp,tcp6,udp,udp6}."""
    remotos: dict[int, tuple[str, int]] = {}
    for linea in texto.splitlines()[1:]:
        partes = linea.split()
        if len(partes) > 9 and partes[9].isdigit():
            remotos[int(partes[9])] = direccion_proc(partes[2])
    return remotos


def _procesos_linux(proc: Path) -> list[tuple[int, int]]:
    pares: list[tuple[int, int]] = []
    for entrada in proc.iterdir():
        if not entrada.name.isdigit():
            continue
        try:
            stat = (entrada / "stat").read_text()
        except OSError:
            continue
        # El nombre va entre parentesis y puede tener espacios: se corta tras el ultimo.
        campos = stat.rsplit(")", 1)[1].split()
        pares.append((int(entrada.name), int(campos[1])))
    return pares


def _conexiones_linux(pids: set[int], proc: Path = Path("/proc")) -> list[Conexion]:
    remotos: dict[int, tuple[str, str, int]] = {}
    for nombre in ("tcp", "tcp6", "udp", "udp6"):
        try:
            texto = (proc / "net" / nombre).read_text()
        except OSError:
            continue
        for inodo, (host, puerto) in leer_proc_net(texto, nombre).items():
            remotos[inodo] = (nombre.rstrip("6").upper(), host, puerto)
    halladas: list[Conexion] = []
    for pid in pids:
        try:
            fds = list((proc / str(pid) / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                destino = os.readlink(fd)
            except OSError:
                continue
            r = remotos.get(int(destino[8:-1])) if destino.startswith("socket:[") else None
            if r is not None and (c := _externa(r[0], (r[1], r[2]), pid)):
                halladas.append(c)
    return halladas


# ---------------------------------------------------------------- macOS


def leer_lsof(texto: str) -> list[Conexion]:
    """Salida de `lsof -nP -i -a -p <pids>`: la columna NAME trae `local->remoto`."""
    halladas: list[Conexion] = []
    for linea in texto.splitlines()[1:]:
        partes = linea.split()
        if len(partes) < 9 or not partes[1].isdigit() or "->" not in partes[8]:
            continue
        protocolo = partes[7] if partes[7] in {"TCP", "UDP"} else "TCP"
        if c := _externa(protocolo, _separar(partes[8].split("->", 1)[1]), int(partes[1])):
            halladas.append(c)
    return halladas


def _procesos_ps() -> list[tuple[int, int]]:
    pares: list[tuple[int, int]] = []
    for linea in _ejecutar("ps", "-axo", "pid=,ppid=").splitlines():
        partes = linea.split()
        if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
            pares.append((int(partes[0]), int(partes[1])))
    return pares


# ---------------------------------------------------------------- comun


def disponible() -> bool:
    return os.name == "nt" or sys.platform.startswith("linux") or sys.platform == "darwin"


def conexiones_externas(raiz: int | None = None) -> list[Conexion]:
    """Conexiones fuera de esta maquina de `raiz` (por defecto, este proceso) y sus hijos."""
    raiz = raiz or os.getpid()
    if os.name == "nt":
        return leer_netstat(_ejecutar("netstat", "-ano"), descendientes(raiz, _procesos_windows()))
    if sys.platform.startswith("linux"):
        return _conexiones_linux(descendientes(raiz, _procesos_linux(Path("/proc"))))
    if sys.platform == "darwin":
        pids = descendientes(raiz, _procesos_ps())
        return leer_lsof(_ejecutar("lsof", "-nP", "-i", "-a", "-p", ",".join(map(str, sorted(pids)))))
    raise NotImplementedError(f"la vigilancia de red no esta implementada en {sys.platform}")
