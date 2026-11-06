"""Guarda as chaves (OpenAI, Claude e o token do GitHub para atualizar) em dados/segredos.json. Copiado do central/servidor/segredos.py.

No Windows cada valor é protegido pelo DPAPI (só este usuário, neste PC, abre). No Linux o
arquivo fica com permissão 600. Nada aqui lê variável de ambiente: a chave da Anthropic do
Windows (`ANTHROPIC_API_KEY`) não pode vazar para cá, porque o Claude Code a tomaria no lugar
da assinatura. As chaves entram só pela tela de configurações ou pelo script de implantar.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
import threading
from ctypes import wintypes
from pathlib import Path

NOMES = ("openai", "claude", "github")
_trava = threading.Lock()


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _Blob(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(dados: bytes, proteger: bool) -> bytes:
    entrada, _manter = _blob(dados)
    saida = _Blob()
    funcao = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
    ok = funcao(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida))
    if not ok:
        raise OSError("O Windows não conseguiu proteger/abrir o segredo (DPAPI).")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def _codificar(valor: str) -> str:
    bruto = valor.encode("utf-8")
    if os.name == "nt":
        return "dpapi:" + base64.b64encode(_dpapi(bruto, True)).decode("ascii")
    return "txt:" + base64.b64encode(bruto).decode("ascii")


def _decodificar(texto: str) -> str | None:
    try:
        tipo, _, resto = texto.partition(":")
        bruto = base64.b64decode(resto)
        if tipo == "dpapi":
            if os.name != "nt":
                return None
            return _dpapi(bruto, False).decode("utf-8")
        if tipo == "txt":
            return bruto.decode("utf-8")
    except (ValueError, OSError):
        pass
    return None


class Segredos:
    def __init__(self, pasta: Path):
        self.arquivo = Path(pasta) / "segredos.json"

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def obter(self, nome: str) -> str:
        if nome not in NOMES:
            return ""
        return _decodificar(self._ler().get(nome, "")) or ""

    def tem(self, nome: str) -> bool:
        return bool(self.obter(nome))

    def guardar(self, nome: str, valor: str) -> None:
        if nome not in NOMES:
            raise ValueError("segredo desconhecido")
        valor = (valor or "").strip()
        with _trava:
            dados = self._ler()
            if valor:
                dados[nome] = _codificar(valor)
            else:
                dados.pop(nome, None)
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            temp = self.arquivo.with_name(f"segredos.{os.getpid()}.{secrets.token_hex(3)}.tmp")
            temp.write_text(json.dumps(dados, indent=1), encoding="utf-8")
            try:
                temp.chmod(0o600)
            except OSError:
                pass
            os.replace(temp, self.arquivo)

    def fim(self, nome: str) -> str:
        """Os 4 últimos caracteres, só para ele reconhecer qual chave está guardada."""
        valor = self.obter(nome)
        return ("…" + valor[-4:]) if len(valor) >= 8 else ""
