"""El recibo: la comparacion contra la linea base, en un formato mostrable.

Regla que gobierna este modulo: **un ahorro solo se anuncia si ambas corridas
pasaron su puerta**. Gastar menos fallando la tarea no es un ahorro, y un recibo
que lo presentara como tal seria exactamente el humo que este proyecto existe
para no producir.

El recibo lleva su propia verificacion -- los identificadores de corrida y el
comando para reproducirla -- para que sea presumible y comprobable a la vez.
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass

from lymi.bench.runner import RunOutcome

ANCHO = 68
"""Ancho total del recibo en terminal, en caracteres."""

BARRA = 30
"""Ancho maximo de las barras. Cabe dentro de ANCHO con etiqueta y cifras."""

CAJA_UNICODE = {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h": "─", "v": "│", "ml": "├", "mr": "┤",
    "bar": "█", "menos": "−",
}
CAJA_ASCII = {
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "h": "-", "v": "|", "ml": "+", "mr": "+",
    "bar": "#", "menos": "-",
}


@dataclass(slots=True)
class Receipt:
    """Comparacion de dos corridas de la misma tarea."""

    task_id: str
    task_title: str
    base: RunOutcome
    test: RunOutcome
    demo: bool = False
    """Respuestas guionadas: los numeros son reproducibles pero NO demuestran
    ahorro real. El recibo lo estampa para que nunca se presente como tal."""

    @property
    def base_tokens(self) -> int:
        return int(self.base.totals.get("remote_tokens", 0))

    @property
    def test_tokens(self) -> int:
        return int(self.test.totals.get("remote_tokens", 0))

    @property
    def local_tokens(self) -> int:
        return int(self.test.totals.get("local_tokens", 0))

    @property
    def base_cost(self) -> float | None:
        return self.base.totals.get("cost_usd")

    @property
    def test_cost(self) -> float | None:
        return self.test.totals.get("cost_usd")

    @property
    def ambas_pasaron(self) -> bool:
        return self.base.gate.passed and self.test.gate.passed

    @property
    def cache_heredada(self) -> int:
        """Cache que lymi leyo de mas respecto de la linea base.

        La linea base corre primero contra el mismo proveedor: su prefijo queda
        en cache y lymi lo lee barato. Ese ahorro no es de lymi, es del orden de
        ejecucion, y un recibo que lo anunciara estaria inflado.
        """
        leida_test = int(self.test.totals.get("cache_read_tokens", 0))
        leida_base = int(self.base.totals.get("cache_read_tokens", 0))
        return max(0, leida_test - leida_base)

    @property
    def ahorro(self) -> float | None:
        """Reduccion de tokens remotos, 0..1. None si no es anunciable."""
        if not self.ambas_pasaron or self.base_tokens == 0 or self.cache_heredada:
            return None
        return 1.0 - (self.test_tokens / self.base_tokens)

    @property
    def motivo_sin_ahorro(self) -> str:
        """Por que no hay cifra que anunciar. Vacio si si la hay."""
        if self.ahorro is not None:
            return ""
        if not self.base.gate.passed:
            return f"la linea base fallo: {self.base.gate.detail}"
        if not self.test.gate.passed:
            return f"lymi fallo: {self.test.gate.detail}"
        if self.cache_heredada:
            return f"lymi leyo {_fmt_tok(self.cache_heredada)} tok de cache que calento la linea base"
        return "la linea base no consumio tokens remotos"

    @property
    def sin_tarifa(self) -> int:
        return int(self.base.totals.get("unpriced_calls", 0)) + int(
            self.test.totals.get("unpriced_calls", 0)
        )

    @property
    def suscripcion(self) -> bool:
        """Alguna corrida se pago con cuota fija: los dolares no son comparables."""
        modos = {self.base.totals.get("billing_mode"), self.test.totals.get("billing_mode")}
        return "subscription" in modos

    @property
    def cache_remota(self) -> int:
        return int(self.base.totals.get("remote_cache_tokens", 0)) + int(
            self.test.totals.get("remote_cache_tokens", 0)
        )

    @property
    def egress(self) -> int:
        """Llamadas de lymi que sacaron datos de la maquina."""
        return int(self.test.totals.get("egress_calls", 0))


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _fmt_usd(v: float | None, *, suscripcion: bool = False) -> str:
    if v is None:
        # Sin dolares por dos razones distintas que el lector tiene que poder
        # distinguir: cuota fija (no aplica) o tarifa desconocida (falta el dato).
        return "suscr." if suscripcion else "n/d"
    return f"${v:.4f}" if v < 1 else f"${v:.2f}"


def soporta_unicode() -> bool:
    """Si la terminal no puede codificar los caracteres de caja, ASCII es mejor
    que una excepcion: un recibo que no se imprime no sirve para nada."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "".join(CAJA_UNICODE.values()).encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def render_terminal(r: Receipt, *, unicode_ok: bool | None = None) -> str:
    """El recibo para la terminal. Texto plano, copiable, sin colores."""
    usar = soporta_unicode() if unicode_ok is None else unicode_ok
    B = CAJA_UNICODE if usar else CAJA_ASCII
    interior = ANCHO - 4

    def fila(texto: str = "") -> str:
        return f"{B['v']} {texto[:interior].ljust(interior)} {B['v']}"

    def fila_barra(etiqueta: str, toks: int, costo: float | None, maximo: int) -> str:
        llenos = max(1, round(BARRA * toks / maximo)) if toks else 0
        izq = f"{etiqueta:<11}" + B["bar"] * llenos
        der = f"{_fmt_tok(toks):>7} tok {_fmt_usd(costo, suscripcion=r.suscripcion):>10}"
        return fila(izq.ljust(interior - len(der)) + der)

    maximo = max(r.base_tokens, r.test_tokens, 1)
    L = [
        B["tl"] + B["h"] * (ANCHO - 2) + B["tr"],
        fila("lymi - recibo de tarea"),
        fila(r.task_title),
        fila(),
        fila_barra("linea base", r.base_tokens, r.base_cost, maximo),
        fila_barra("lymi", r.test_tokens, r.test_cost, maximo),
        fila(),
    ]

    if r.ahorro is not None:
        L.append(fila(f"{B['menos']}{r.ahorro * 100:.0f}% tokens remotos"))
        L.append(fila("ambas corridas pasaron su puerta de correctitud"))
    else:
        L.append(fila("SIN AHORRO ANUNCIABLE"))
        L.append(fila(r.motivo_sin_ahorro))

    if r.local_tokens:
        L.append(fila(f"{_fmt_tok(r.local_tokens)} tok en local: no salieron de tu maquina"))
    if r.egress:
        L.append(fila(f"{r.egress} llamadas de lymi si salieron (destino y hash en el ledger)"))
    if r.cache_remota:
        L.append(fila(f"los tokens remotos incluyen {_fmt_tok(r.cache_remota)} de cache"))
    if r.suscripcion:
        L.append(fila("suscripcion: se compara en tokens, no en dolares"))
    if r.sin_tarifa:
        L.append(fila(f"! {r.sin_tarifa} llamadas sin tarifa: el costo esta incompleto"))
    if r.demo:
        L.append(fila("MODO DEMO - guionado, no demuestra ahorro real"))

    L.append(B["ml"] + B["h"] * (ANCHO - 2) + B["mr"])
    L.append(fila(f"{r.base.run_id} vs {r.test.run_id}"))
    L.append(fila(f"reproduce: lymi bench {r.task_id}"))
    L.append(B["bl"] + B["h"] * (ANCHO - 2) + B["br"])
    return "\n".join(L)


def render_card_html(r: Receipt) -> str:
    """Tarjeta compartible, pensada para captura de pantalla.

    Incluye la verificacion a proposito: sin los identificadores de corrida y el
    comando para reproducirla, la tarjeta seria una afirmacion mas.
    """
    maximo = max(r.base_tokens, r.test_tokens, 1)

    if r.ahorro is not None:
        titular, color = f"&minus;{r.ahorro * 100:.0f}%", "#56c9a3"
        subtitulo = "tokens remotos frente a la linea base"
        sello = "ambas corridas pasaron su puerta de correctitud"
    else:
        titular, color = "sin ahorro", "#d9705b"
        subtitulo = "no hay cifra anunciable en esta corrida"
        sello = html.escape(r.motivo_sin_ahorro)

    banda = (
        '<div class="demo">MODO DEMO &middot; respuestas guionadas &middot; '
        "no demuestra ahorro real</div>"
        if r.demo
        else ""
    )
    local = (
        f'<div class="local">{_fmt_tok(r.local_tokens)} tokens procesados en tu '
        "m&aacute;quina &middot; no salieron de ella</div>"
        if r.local_tokens
        else ""
    )

    def barra(etiqueta: str, toks: int, costo: float | None, relleno: str) -> str:
        return (
            f'<div class="row"><div class="lbl">{etiqueta}</div>'
            f'<div class="track"><div class="fill" style="width:{100 * toks / maximo:.1f}%;'
            f'background:{relleno}"></div></div>'
            f'<div class="num">{_fmt_tok(toks)} tok &middot; '
            f"{_fmt_usd(costo, suscripcion=r.suscripcion)}</div></div>"
        )

    return f"""<title>Recibo &middot; {html.escape(r.task_title)}</title>
<style>
  :root {{ --bg:#0c0c0b; --panel:#121210; --line:#232320; --tx:#e8e6e1;
           --dim:#7d7b74; --faint:#4d4b45; --green:#56c9a3; }}
  body {{ background:var(--bg); color:var(--tx); margin:0; padding:32px;
          font-family:"IBM Plex Sans",system-ui,sans-serif;
          display:flex; align-items:center; justify-content:center; min-height:100vh; }}
  .card {{ width:min(620px,100%); background:var(--panel); border:1px solid var(--line);
           border-radius:14px; overflow:hidden; }}
  .demo {{ background:#2e2419; color:#d9a45b; font-size:11px; letter-spacing:.09em;
           padding:9px 26px; font-family:ui-monospace,Menlo,monospace; }}
  .head {{ padding:22px 26px 0; }}
  .brand {{ font-size:11px; letter-spacing:.18em; color:var(--faint);
            font-family:ui-monospace,Menlo,monospace; }}
  h1 {{ font-size:17px; font-weight:500; margin:8px 0 0; }}
  .big {{ font-size:60px; line-height:1; margin:22px 26px 2px; color:{color};
          font-family:Georgia,serif; }}
  .sub {{ margin:0 26px 20px; font-size:12.5px; color:var(--dim); }}
  .rows {{ padding:0 26px; display:flex; flex-direction:column; gap:11px; }}
  .row {{ display:flex; align-items:center; gap:13px; }}
  .lbl {{ width:78px; font-size:12px; color:var(--dim); flex-shrink:0; }}
  .track {{ flex-grow:1; height:9px; background:#1c1c19; border-radius:5px; overflow:hidden; }}
  .fill {{ height:9px; border-radius:5px; }}
  .num {{ width:132px; text-align:right; font-size:12px; color:var(--dim); flex-shrink:0;
          font-family:ui-monospace,Menlo,monospace; }}
  .local {{ margin:18px 26px 0; font-size:12px; color:var(--green); }}
  .seal {{ margin:10px 26px 20px; font-size:12px; color:var(--dim); }}
  .foot {{ border-top:1px solid var(--line); padding:13px 26px; font-size:11px;
           color:var(--faint); font-family:ui-monospace,Menlo,monospace;
           display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
</style>
<div class="card">
  {banda}
  <div class="head">
    <div class="brand">LYMI &middot; RECIBO DE TAREA</div>
    <h1>{html.escape(r.task_title)}</h1>
  </div>
  <div class="big">{titular}</div>
  <div class="sub">{subtitulo}</div>
  <div class="rows">
    {barra("linea base", r.base_tokens, r.base_cost, "#55534d")}
    {barra("lymi", r.test_tokens, r.test_cost, "var(--green)")}
  </div>
  {local}
  <div class="seal">{sello}</div>
  <div class="foot">
    <span>corridas {r.base.run_id} &middot; {r.test.run_id}</span>
    <span>reproduce: lymi bench {r.task_id}</span>
  </div>
</div>
"""
