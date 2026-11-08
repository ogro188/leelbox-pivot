#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Funciones puras compartidas entre detectores y orquestador."""


def clamp_0_100(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 100:
        return 100.0
    return v


def build_pattern_key(detector: str, direction: int, key_level: float) -> str:
    return f"{detector}|{direction}|{key_level:.10f}"
