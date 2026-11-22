"""Normalización de CARGA tal como la hace TranvíaOnline.

`getCargaNormalizada` no trata CARGA como un porcentaje. Es un entero crudo
que la web convierte a un porcentaje mostrado con esta escala. A partir de
80 (valor crudo, no el porcentaje) el panel pasa a rojo y recomienda esperar.
"""

from __future__ import annotations

# (límite exclusivo, porcentaje mostrado). El resto, 100.
CARGA_STEPS: tuple[tuple[int, int], ...] = (
    (5, 3),
    (8, 7),
    (11, 10),
    (14, 14),
    (17, 18),
    (20, 22),
    (23, 25),
    (26, 29),
    (29, 33),
    (32, 36),
    (35, 40),
    (38, 44),
    (41, 48),
    (44, 51),
    (47, 55),
    (50, 59),
    (53, 62),
    (56, 66),
    (59, 70),
    (62, 74),
    (65, 77),
    (68, 81),
    (71, 85),
    (74, 89),
    (77, 92),
    (80, 96),
)
HIGH_CARGA = 80

OCCUPANCY_MEANING = (
    "CARGA es un índice crudo de TranvíaOnline, no un porcentaje. "
    "La web lo convierte con getCargaNormalizada al porcentaje que muestra. "
    "Si CARGA es 80 o más, el aviso es de ocupación muy alta. "
    "Sin fila reciente, la ocupación es desconocida."
)


def normalize_carga(raw: int) -> int:
    """Porcentaje que mostraría TranvíaOnline para ese CARGA."""
    for limit, shown in CARGA_STEPS:
        if raw < limit:
            return shown
    return 100


def occupancy_texts(raw: int) -> tuple[str, str]:
    """Texto normal y advertencia, como getMsgPanelOcupacion y getMsgPanelAdvertencia."""
    shown = normalize_carga(raw)
    if raw >= HIGH_CARGA:
        warning = (
            f"* OCUPACIÓN MUY ALTA ({shown}%): Límite de capacidad máxima, "
            "se recomienda esperar al próximo tranvía."
        )
        return "", warning
    return f"OCUPACIÓN: {shown}%", ""
