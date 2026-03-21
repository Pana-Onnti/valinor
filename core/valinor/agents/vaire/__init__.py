"""
Vairë Agent — Frontend rendering agent para KO Reports.

Toma el output del Narrador y produce:
  - HTML renderizado (KO Report v2)
  - PDF buffer para email digest
  - Summary card para WhatsApp

Nombre: Vairë — la tejedora de historias en Tolkien.
"""

from .agent import VaireAgent

__all__ = ["VaireAgent"]
