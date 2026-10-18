"""Genera el icono de lymi en .png, .ico (Windows) e .icns (macOS), sin dependencias.

Un cuadrado redondeado del color de acento con una "l" blanca y un punto: dibujado
con funciones de distancia, asi el borde sale suavizado en cualquier tamano.

    uv run python empaquetado/icono.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FONDO = (79, 70, 229)  # el --acento de la interfaz
TINTA = (255, 255, 255)


def _caja_redondeada(px: float, py: float, cx: float, cy: float, mx: float, my: float, r: float) -> float:
    qx, qy = abs(px - cx) - mx + r, abs(py - cy) - my + r
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _cobertura(distancia: float, borde: float) -> float:
    return min(1.0, max(0.0, 0.5 - distancia / borde))


def pixeles(n: int) -> bytes:
    """RGBA de n x n."""
    filas = bytearray()
    borde = 1.0
    for y in range(n):
        filas.append(0)  # filtro PNG: ninguno
        for x in range(n):
            px, py = x + 0.5, y + 0.5
            fondo = _cobertura(_caja_redondeada(px, py, n / 2, n / 2, n * 0.46, n * 0.46, n * 0.22), borde)
            barra = _cobertura(_caja_redondeada(px, py, n * 0.42, n * 0.47, n * 0.075, n * 0.27, n * 0.075), borde)
            punto = _cobertura(math.hypot(px - n * 0.64, py - n * 0.68) - n * 0.085, borde)
            tinta = max(barra, punto)
            r, g, b = (round(f * (1 - tinta) + t * tinta) for f, t in zip(FONDO, TINTA, strict=True))
            filas += bytes((r, g, b, round(255 * fondo)))
    return bytes(filas)


def png(n: int) -> bytes:
    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    cabecera = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", cabecera) + trozo(b"IDAT", zlib.compress(pixeles(n), 9)) + trozo(b"IEND", b"")


def ico(tamanos: list[int]) -> bytes:
    imagenes = [png(n) for n in tamanos]
    cabecera = struct.pack("<HHH", 0, 1, len(imagenes))
    desplazamiento = 6 + 16 * len(imagenes)
    entradas = b""
    for n, datos in zip(tamanos, imagenes, strict=True):
        entradas += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(datos), desplazamiento)
        desplazamiento += len(datos)
    return cabecera + entradas + b"".join(imagenes)


def icns() -> bytes:
    tipos = [(b"ic07", 128), (b"ic08", 256), (b"ic09", 512)]
    cuerpo = b"".join(t + struct.pack(">I", 8 + len(d)) + d for t, d in ((t, png(n)) for t, n in tipos))
    return b"icns" + struct.pack(">I", 8 + len(cuerpo)) + cuerpo


def main() -> None:
    (AQUI / "lymi.png").write_bytes(png(256))
    (AQUI / "lymi.ico").write_bytes(ico([16, 24, 32, 48, 64, 128, 256]))
    (AQUI / "lymi.icns").write_bytes(icns())
    print("lymi.png, lymi.ico y lymi.icns en", AQUI)


if __name__ == "__main__":
    main()
