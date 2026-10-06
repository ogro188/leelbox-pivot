#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifica que los tokens de color de frontend/ cumplan WCAG 2.1 AA.

Regla (README, diseno #3: "Metrics Require Commands"): ningun numero en la
documentacion sin un comando que lo produzca. Este script ES ese comando.

  python3 scripts/check_contrast.py

Contraste minimo exigido:
  - texto normal ....... 4.5:1  (WCAG 1.4.3 AA)
  - bordes de control ... 3.0:1  (WCAG 1.4.11 non-text)

`base.line` es un hairline decorativo (divisores, grilla): se reporta como
informativo porque la estructura de regiones no depende de el para
comprender el contenido. Los controles interactivos usan `base.edge`, que si
se exige a 3:1.

Sale con codigo != 0 si algun token obligatorio falla.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
TEXT_MIN = 4.5
NONTEXT_MIN = 3.0

# Superficies sobre las que se renderiza texto (fondo, panel, panel anidado)
SURFACES = ("base.bg", "base.panel", "base.panel2")

# Tokens que siempre se usan como texto
TEXT_TOKENS = (
    "text.primary",
    "text.secondary",
    "text.muted",
    "brand.cyan",
    "signal.long",
    "signal.short",
    "state.ok",
    "state.warn",
    "state.error",
)

# Tokens que se usan como borde de control interactivo (no texto)
NONTEXT_TOKENS = ("base.edge",)

# Hairlines decorativos: se reportan pero no fallan el build
DECORATIVE_TOKENS = ("base.line",)


def _srgb(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (_srgb(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    light, dark = max(la, lb), min(la, lb)
    return (light + 0.05) / (dark + 0.05)


def load_constants() -> dict[str, str]:
    """LEE src/theme.ts -> {SIGNAL_LONG: '#...', ...}"""
    text = (FRONTEND / "src" / "theme.ts").read_text(encoding="utf-8")
    return dict(re.findall(r"export const (\w+)\s*=\s*'(#[0-9A-Fa-f]{6})'", text))


def load_colors(constants: dict[str, str]) -> dict[str, str]:
    """LEE tailwind.config.js -> {'base.bg': '#...', 'signal.short': '#...', ...}"""
    text = (FRONTEND / "tailwind.config.js").read_text(encoding="utf-8")
    start = text.find("colors:")
    if start == -1:
        raise SystemExit("FAIL: no se encontro `colors:` en tailwind.config.js")

    # Aislar el bloque colors: { ... } contando llaves
    i = text.find("{", start)
    depth, end = 0, i
    for pos in range(i, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                end = pos
                break
    # Quitar comentarios // para no matchear patterns dentro de ellos
    block = re.sub(r"//[^\n]*", "", text[i + 1 : end])

    out: dict[str, str] = {}
    # Grupos anidados en una linea: base: { bg: '#0B0E14', panel: '#141922' }
    for name, body in re.findall(r"(\w+)\s*:\s*\{([^{}]*)\}", block):
        for key, value in re.findall(r"(\w+)\s*:\s*['\"](#[0-9A-Fa-f]{3,6})['\"]", body):
            out[f"{name}.{key}"] = value
        # Valores que son constantes importadas de theme.ts (signal.long = SIGNAL_LONG)
        for key, const in re.findall(r"(\w+)\s*:\s*([A-Z][A-Z0-9_]+)", body):
            if const in constants:
                out[f"{name}.{key}"] = constants[const]
    # Entradas planas fuera de grupo (si las hubiera)
    for key, value in re.findall(r"^\s*(\w+)\s*:\s*'(#[0-9A-Fa-f]{6})'", block, re.M):
        out.setdefault(key, value)
    return out


def main() -> int:
    if not (FRONTEND / "tailwind.config.js").exists():
        print(f"FAIL: no existe {FRONTEND}/tailwind.config.js")
        return 1

    colors = load_colors(load_constants())
    failures: list[str] = []
    rows: list[tuple[str, str, str, float, float, str]] = []

    def check(tokens: tuple[str, ...], minimum: float, label: str, hard: bool = True) -> None:
        for tok in tokens:
            if tok not in colors:
                if hard:
                    failures.append(f"{label}: token '{tok}' no existe en la paleta")
                continue
            for surf in SURFACES:
                if surf not in colors:
                    failures.append(f"{label}: superficie '{surf}' no existe")
                    continue
                ratio = contrast(colors[tok], colors[surf])
                ok = ratio >= minimum
                state = "OK" if ok else ("FAIL" if hard else "info")
                rows.append((label, tok, surf, ratio, minimum, state))
                if not ok and hard:
                    failures.append(
                        f"{label}: {tok} ({colors[tok]}) sobre {surf} "
                        f"({colors[surf]}) = {ratio:.2f}:1 < {minimum}:1"
                    )

    check(TEXT_TOKENS, TEXT_MIN, "texto")
    check(NONTEXT_TOKENS, NONTEXT_MIN, "control")
    check(DECORATIVE_TOKENS, NONTEXT_MIN, "hairline", hard=False)

    width = max(len(r[1]) + len(r[2]) for r in rows) + 4
    print(f"{'clase':9} {'par':<{width}} {'ratio':>7}  {'min':>5}  estado")
    print("-" * (width + 34))
    for label, tok, surf, ratio, minimum, state in rows:
        par = f"{tok} / {surf}"
        print(f"{label:9} {par:<{width}} {ratio:>6.2f}:1  {minimum:>4}:1  {state}")

    print()
    if failures:
        print(f"FAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("OK: todos los tokens cumplen WCAG 2.1 AA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
