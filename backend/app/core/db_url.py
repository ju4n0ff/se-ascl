"""Normalización de ``DATABASE_URL`` y ``connect_args`` de asyncpg (funciones puras).

Admite las URL tal como se copian de Supabase o Render (``postgres://``,
``postgresql://``, ``?sslmode=require``, ``?pgbouncer=true``). asyncpg no acepta
``sslmode`` ni los parámetros de otros clientes: se retiran de la URL y se traducen.

Ningún mensaje de error de este módulo incluye la URL, porque trae la contraseña.
"""
from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import URL, make_url

DRIVER_ASYNC = "postgresql+asyncpg"
DRIVER_SYNC = "postgresql+psycopg2"
DIALECTOS_POSTGRES = {"postgres", "postgresql"}

SUFIJOS_SUPABASE = (".supabase.co", ".supabase.com")
SUFIJO_POOLER_SUPABASE = ".pooler.supabase.com"
PUERTO_TRANSACTION_POOLER = 6543

SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
# Parámetros de otros clientes (Prisma, libpq) que asyncpg rechazaría como kwargs.
PARAMETROS_AJENOS = {"sslmode", "ssl", "pgbouncer", "connection_limit", "channel_binding"}


@dataclass(frozen=True)
class DatosConexion:
    url: URL
    sslmode: str | None  # lo que pedía la URL, o None
    pgbouncer: bool  # la URL traía ?pgbouncer=true

    @property
    def host(self) -> str:
        return (self.url.host or "").lower().rstrip(".")

    @property
    def es_supabase(self) -> bool:
        return self.host.endswith(SUFIJOS_SUPABASE)

    @property
    def usa_pooler(self) -> bool:
        return (
            self.pgbouncer
            or self.host.endswith(SUFIJO_POOLER_SUPABASE)
            or self.url.port == PUERTO_TRANSACTION_POOLER
        )


def _parametro(url: URL, nombre: str) -> str | None:
    valor = url.query.get(nombre)
    if isinstance(valor, tuple):  # repetido en la URL: gana el último, como en libpq
        valor = valor[-1]
    return valor.strip().lower() if valor is not None else None


def analizar_url(cruda: str, driver: str = DRIVER_ASYNC) -> DatosConexion:
    try:
        url = make_url(cruda.strip())
    except Exception:
        # "from None": la excepción original podría arrastrar la URL con la contraseña.
        raise ValueError(
            "URL de base de datos inválida (¿falta codificar la contraseña con %XX?)"
        ) from None
    if url.drivername.split("+")[0] not in DIALECTOS_POSTGRES:
        raise ValueError("La URL de base de datos debe ser de PostgreSQL")

    sslmode = _parametro(url, "sslmode") or _parametro(url, "ssl")
    if sslmode in {"true", "1"}:
        sslmode = "require"
    if sslmode is not None and sslmode not in SSLMODES:
        raise ValueError("sslmode no reconocido en la URL de base de datos")
    if "sslrootcert" in url.query:
        raise ValueError("Usa DB_SSL_ROOT_CERT en vez de 'sslrootcert' en la URL")

    return DatosConexion(
        url=url.difference_update_query(PARAMETROS_AJENOS).set(drivername=driver),
        sslmode=sslmode,
        pgbouncer=_parametro(url, "pgbouncer") in {"true", "1"},
    )


def texto(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def ssl_efectivo(datos: DatosConexion, db_ssl: bool | None) -> bool:
    """``DB_SSL`` explícito > ``sslmode`` de la URL > host de Supabase."""
    if db_ssl is not None:
        return db_ssl
    if datos.sslmode == "disable":
        return False
    if datos.sslmode in {"require", "verify-ca", "verify-full"}:
        return True
    return datos.es_supabase


def argumento_ssl(sslmode: str | None, ca: Path | None) -> str | ssl.SSLContext:
    """Valor de ``connect_args["ssl"]`` para asyncpg.

    * Con CA propia (``DB_SSL_ROOT_CERT``): verifica cadena **y** hostname.
    * ``verify-*`` en la URL sin CA propia: igual, contra las CA del sistema. Nunca se
      degrada en silencio a ``require``.
    * ``"require"``: cifra, pero no autentica al servidor (semántica de libpq).
    """
    if ca is not None:
        return ssl.create_default_context(cafile=str(ca))
    if sslmode in {"verify-ca", "verify-full"}:
        return ssl.create_default_context()
    return "require"


def nombre_sentencia() -> str:
    return f"__asyncpg_{uuid4().hex}__"


def construir_connect_args(
    *, usar_ssl: bool, usar_pgbouncer: bool, sslmode: str | None = None, ca: Path | None = None
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if usar_ssl:
        args["ssl"] = argumento_ssl(sslmode, ca)
    if usar_pgbouncer:
        args["statement_cache_size"] = 0  # caché de asyncpg
        args["prepared_statement_cache_size"] = 0  # caché del dialecto de SQLAlchemy
        # Con ambos cachés en 0, SQLAlchemy igual crea sentencias con nombre secuencial
        # (__asyncpg_stmt_1__). El contador reinicia con cada proceso: tras un redeploy, o con
        # otro cliente en el mismo backend del pooler, los nombres chocarían.
        args["prepared_statement_name_func"] = nombre_sentencia
    return args


def normalizar_url_sync(cruda: str) -> str:
    """URL para psycopg2 (libpq sí entiende ``sslmode``, así que se conserva)."""
    datos = analizar_url(cruda, DRIVER_SYNC)
    sslmode = datos.sslmode or ("require" if datos.es_supabase else None)
    url = datos.url.update_query_dict({"sslmode": sslmode}) if sslmode else datos.url
    return texto(url)
