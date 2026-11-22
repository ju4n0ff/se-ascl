"""Logging con ``request_id`` correlacionado.

Política: nunca loguear contraseñas, tokens ``Authorization`` ni landmarks.
"""
from __future__ import annotations

import logging

from app.core.middleware import request_id_ctx

FORMATO = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configurar_logging(debug: bool) -> None:
    raiz = logging.getLogger()
    if any(isinstance(f, RequestIdFilter) for h in raiz.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMATO))
    handler.addFilter(RequestIdFilter())
    raiz.addHandler(handler)
    raiz.setLevel(logging.DEBUG if debug else logging.INFO)
    # TensorFlow y asyncio son muy verbosos en DEBUG.
    for ruidoso in ("tensorflow", "absl", "asyncio", "h5py"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
