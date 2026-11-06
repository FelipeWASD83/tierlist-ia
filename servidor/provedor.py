"""O que a OpenAI (Responses) e o Claude (Messages) têm em comum, sem fazer rede.

Este arquivo é CÓPIA IDÊNTICA nos projetos Python que falam com IA (contato-ia,
namorada-ia, servidor-ia, zelador, tradutor-ln, diddy-tensei). Mudou aqui,
muda nos outros: o teste `test_provedor.py` também é igual em todos.

O que mora aqui:
- de qual lado é um modelo (`claude-*` vai pra Anthropic, o resto pra OpenAI);
- o par de cada modelo do outro lado, para quando um lado ficar sem crédito;
- como reconhecer "sem crédito" nos dois lados e o disjuntor que lembra disso;
- a conversão do pedido do formato da OpenAI para o do Claude, e da resposta de volta;
- o preço de cada modelo.

Nada aqui chama API nem lê arquivo.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field
from typing import Callable

ANTHROPIC_VERSAO = "2023-06-01"
CACHE = {"type": "ephemeral"}
ABERTURA = "[A conversa começa aqui.]"
CONTINUE = "[Continue a partir daqui.]"
SEGUNDOS_DO_DISJUNTOR = 30 * 60

# ── Qual é o lado de um modelo ───────────────────────────────────────────────


def eh_claude(modelo: str) -> bool:
    return str(modelo or "").strip().lower().startswith("claude")


def provedor_de(modelo: str) -> str:
    return "claude" if eh_claude(modelo) else "openai"


# Par de cada modelo do outro lado: mesma faixa de preço e de inteligência
# (.claude/pesquisas/modelos-claude.md e modelos-openai.md, de 14/10/2026).
PARES = {
    "gpt-6-luna": "claude-haiku-5-5",
    "gpt-6.1-sol": "claude-sonnet-5-5",
    "gpt-6-sol": "claude-sonnet-5-5",
    "gpt-6-astra": "claude-opus-5-5",
    "claude-haiku-5-5": "gpt-6-luna",
    "claude-sonnet-5-5": "gpt-6.1-sol",
    "claude-opus-5-5": "gpt-6-astra",
    "claude-fable-5-1": "gpt-6-astra",
    "claude-fable-5": "gpt-6-astra",
    "claude-opus-5": "gpt-6-astra",
    "claude-opus-4-8": "gpt-6-astra",
    "claude-sonnet-5": "gpt-6.1-sol",
    "claude-sonnet-4-6": "gpt-6.1-sol",
    "claude-haiku-4-5": "gpt-6-luna",
    "gpt-5.6-luna": "claude-haiku-5-5",
    "gpt-5.6-terra": "claude-sonnet-5-5",
    "gpt-5.6-sol": "claude-sonnet-5-5",
}
RESERVA_PADRAO = {"openai": "claude-haiku-5-5", "claude": "gpt-6-luna"}
SEM_RESERVA = ("nenhuma", "nenhum", "off", "desligada", "desligado", "não", "nao", "false")


def reserva_de(modelo: str, configurada: str | None = "auto") -> str | None:
    """O modelo do outro lado que assume quando o principal fica sem crédito.

    `configurada`: "auto" (o par da tabela), um id do OUTRO lado, ou "nenhuma".
    Id do mesmo lado não serve de reserva por crédito (acabou o crédito de um
    lado, o do mesmo lado acabou junto): cai no par da tabela.
    """
    escolha = str(configurada or "auto").strip()
    if escolha.lower() in SEM_RESERVA:
        return None
    if escolha.lower() != "auto" and provedor_de(escolha) != provedor_de(modelo):
        return escolha
    sem_data = re.sub(r"-\d{8}$", "", str(modelo or "").strip().lower())
    return PARES.get(modelo) or PARES.get(sem_data) or RESERVA_PADRAO[provedor_de(modelo)]


# ── Preço (US$ por 1 milhão de tokens): entrada, leitura do cache, escrita do cache, saída ───

PRECOS = {
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    "gpt-6.1-sol": (2.00, 0.10, 2.50, 10.00),
    "gpt-6-sol": (2.00, 0.20, 2.50, 10.00),
    "gpt-6-astra": (10.00, 1.00, 12.50, 50.00),
    "gpt-5.6-luna": (0.20, 0.02, 0.25, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 2.50, 12.00),
    "gpt-5.6-sol": (4.00, 0.40, 5.00, 20.00),
    "gpt-5-mini": (0.25, 0.025, 0.25, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.05, 0.40),
    "gpt-4o-mini": (0.15, 0.075, 0.15, 0.60),
    "gpt-4o": (2.50, 1.25, 2.50, 10.00),
    "claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),
    "claude-sonnet-5-5": (2.00, 0.10, 2.50, 10.00),
    "claude-opus-5-5": (4.00, 0.20, 5.00, 20.00),
    "claude-fable-5-1": (10.00, 0.25, 12.50, 50.00),
    "claude-fable-5": (10.00, 1.00, 12.50, 50.00),
    "claude-sonnet-5": (2.00, 0.20, 2.50, 10.00),
    "claude-opus-5": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-8": (5.00, 0.50, 6.25, 25.00),
    "claude-sonnet-4-6": (3.00, 0.30, 3.75, 15.00),
    "claude-haiku-4-5": (1.00, 0.10, 1.25, 5.00),
}


def preco_de(modelo: str) -> tuple[float, float, float, float] | None:
    """Preço do modelo; aceita id com data no fim (claude-haiku-4-5-20251001)."""
    modelo = str(modelo or "").strip().lower()
    if modelo in PRECOS:
        return PRECOS[modelo]
    sem_data = re.sub(r"-\d{8}$", "", modelo)
    return PRECOS.get(sem_data)


def custo(modelo: str, uso: dict | None) -> float | None:
    """Custo em dólares de um `uso` já no formato da OpenAI (ver `uso_normalizado`). None se o modelo não tem preço."""
    preco = preco_de(modelo)
    if preco is None or not uso:
        return None
    entrada, lido, escrita, saida = preco
    total = int(uso.get("input_tokens") or 0)
    detalhes = uso.get("input_tokens_details") or {}
    cache = min(int(detalhes.get("cached_tokens") or 0), total)
    gravado = min(int(detalhes.get("cache_write_tokens") or 0), total - cache)
    cheio = total - cache - gravado
    return (cheio * entrada + cache * lido + gravado * escrita + int(uso.get("output_tokens") or 0) * saida) / 1_000_000


# ── Sem crédito ──────────────────────────────────────────────────────────────

_SINAIS_DE_SEM_CREDITO = (
    "insufficient_quota",            # OpenAI: 429 com code/type insufficient_quota
    "exceeded your current quota",   # OpenAI: mesma situação, na mensagem
    "billing_hard_limit",            # OpenAI: teto de gasto da conta
    "billing_not_active",            # OpenAI: conta sem forma de pagamento
    "billing_error",                 # Anthropic: type do erro 402
    "credit balance is too low",     # Anthropic: 400 invalid_request_error
    "credit balance too low",
    "specified api usage limits",    # Anthropic: teto de gasto do workspace
    "out of credits",
    "insufficient credit",
)


def falta_de_credito(status: int, dados: dict | None) -> bool:
    """A resposta de erro diz que o crédito ou o teto de gasto da conta acabou?

    Limite por minuto (429 rate_limit), servidor ocupado (5xx, 529) e chave
    errada (401) NÃO são falta de crédito: esses continuam sendo erro.
    """
    if status == 402:
        return True
    if status not in (400, 401, 403, 429):
        return False
    erro = (dados or {}).get("error")
    if isinstance(erro, dict):
        texto = f"{erro.get('code') or ''} {erro.get('type') or ''} {erro.get('message') or ''}"
    else:
        texto = str(erro or "")
    texto = texto.lower()
    return any(sinal in texto for sinal in _SINAIS_DE_SEM_CREDITO)


class Disjuntor:
    """Lembra que um lado ficou sem crédito, para não gastar uma viagem perdida a cada pedido.

    Passado o prazo, o lado volta a ser tentado sozinho (o crédito pode ter voltado).
    """

    def __init__(self, segundos: float = SEGUNDOS_DO_DISJUNTOR, relogio: Callable[[], float] = time.monotonic):
        self.segundos = segundos
        self._relogio = relogio
        self._ate: dict[str, float] = {}

    def abrir(self, lado: str) -> None:
        self._ate[lado] = self._relogio() + self.segundos

    def fechar(self, lado: str) -> None:
        self._ate.pop(lado, None)

    def aberto(self, lado: str) -> bool:
        ate = self._ate.get(lado)
        if ate is None:
            return False
        if self._relogio() >= ate:
            # pop e não del: duas threads vencendo o prazo juntas davam KeyError na segunda.
            self._ate.pop(lado, None)
            return False
        return True

    def minutos_restantes(self, lado: str) -> int:
        ate = self._ate.get(lado)
        if ate is None:
            return 0
        return max(0, int((ate - self._relogio() + 59) // 60))


# ── Raciocínio: o esforço da OpenAI traduzido para o Claude ──────────────────

ESFORCOS = ("none", "low", "medium", "high", "xhigh", "max")


def _familia_claude(modelo: str) -> str:
    """Agrupa o id do Claude pelo que muda no pedido. Id desconhecido cai em "antigo" (não manda esforço nem pensamento)."""
    m = str(modelo or "").lower()
    m = re.sub(r"-\d{8}$", "", m)
    if m.startswith("claude-haiku-5"):
        return "haiku5"
    if m.startswith("claude-sonnet-5-5"):
        return "sonnet55"
    if m.startswith(("claude-opus-5-5", "claude-fable", "claude-mythos")):
        return "sempre_pensa"
    if m.startswith(("claude-sonnet-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7")):
        return "desliga"
    if m.startswith(("claude-opus-4-6", "claude-sonnet-4-6")):
        return "adaptativo"
    return "antigo"


def parametros_de_raciocinio(modelo: str, esforco: str) -> dict:
    """Pedaços do corpo do Claude (`thinking` e `output_config.effort`) para este modelo e esforço.

    - esforço "none" quer dizer "não pensar": o Haiku 5.5 e os que desligam usam
      `thinking: disabled`; o Sonnet 5.5 recusa o `disabled` e usa `between_tools`;
      o Opus 5.5 e o Fable não desligam, então vão no esforço mais baixo.
    - os outros esforços ligam o pensamento adaptativo com `output_config.effort`.
    - modelo antigo (Haiku 4.5, Sonnet 4.5...) não aceita esforço: sai sem nada.
    - nunca vai temperature, top_p nem top_k (400 do Claude 4.7 em diante).
    """
    familia = _familia_claude(modelo)
    if familia == "antigo":
        return {}
    esforco = esforco if esforco in ESFORCOS else "low"
    if esforco == "none":
        if familia in ("haiku5", "desliga"):
            return {"thinking": {"type": "disabled"}}
        if familia == "sonnet55":
            return {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
        if familia == "sempre_pensa":
            return {"output_config": {"effort": "low"}}
        return {"output_config": {"effort": "low"}}
    if familia == "adaptativo" and esforco == "xhigh":
        esforco = "high"   # o Opus 4.6 e o Sonnet 4.6 não têm xhigh
    return {"thinking": {"type": "adaptive"}, "output_config": {"effort": esforco}}


# ── Pedido: formato da OpenAI → formato do Claude ────────────────────────────

_TIPOS_DE_TEXTO = ("input_text", "output_text", "text")
_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.*)$", re.S)


def _texto_de(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo
    partes = []
    for parte in conteudo or []:
        if isinstance(parte, dict) and parte.get("type") in _TIPOS_DE_TEXTO and parte.get("text"):
            partes.append(parte["text"])
    return "\n".join(partes)


def _bloco_de_imagem(parte: dict) -> dict | None:
    url = parte.get("image_url")
    if isinstance(url, dict):
        url = url.get("url")
    if not isinstance(url, str) or not url:
        return None
    achou = _DATA_URL.match(url)
    if achou:
        return {"type": "image", "source": {"type": "base64", "media_type": achou.group(1), "data": achou.group(2)}}
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _blocos_de(conteudo) -> list[dict]:
    if isinstance(conteudo, str):
        return [{"type": "text", "text": conteudo}] if conteudo.strip() else []
    blocos = []
    for parte in conteudo or []:
        if not isinstance(parte, dict):
            continue
        tipo = parte.get("type")
        if tipo in _TIPOS_DE_TEXTO:
            if (parte.get("text") or "").strip():
                blocos.append({"type": "text", "text": parte["text"]})
        elif tipo in ("input_image", "image_url"):
            bloco = _bloco_de_imagem(parte)
            if bloco:
                blocos.append(bloco)
        elif tipo == "image" and isinstance(parte.get("source"), dict):
            blocos.append(parte)
    return blocos


def converter_entrada(instrucoes: str | None, entrada) -> tuple[list[dict], list[dict]]:
    """(system, messages) do Claude a partir de `instructions` + `input` da Responses.

    - `developer` e `system` antes da primeira fala viram o `system`;
    - `developer` depois de uma fala do usuário (a nota de bastidor, a hora) vai
      como mais um bloco de texto NA MESMA mensagem dele, depois do texto dele;
    - o Claude não aceita começar pelo assistente nem terminar nele (sem prefill),
      então entra uma abertura ou um "continue" neutro nesses casos;
    - o ponto de cache fica no último bloco ANTES dessas notas, e no fim do
      `system`: o que varia a cada pedido fica depois do cache, como na OpenAI.
      Vale também quando a nota vem depois de uma fala do assistente (o pedido
      do servidor-ia): a nota vira um turno do usuário só dela, e o cache fica
      na fala do assistente.
    """
    sistema = [instrucoes.strip()] if instrucoes and instrucoes.strip() else []
    itens = [{"role": "user", "content": entrada}] if isinstance(entrada, str) else list(entrada or [])
    mensagens: list[dict] = []
    pendentes: list[dict] = []
    ultimo_do_sistema: str | None = None    # o último `developer` que foi parar no system
    for item in itens:
        if not isinstance(item, dict):
            continue
        papel = item.get("role")
        if papel in ("developer", "system"):
            texto = _texto_de(item.get("content")).strip()
            if not texto:
                continue
            nota = {"type": "text", "text": texto}
            if not mensagens:
                sistema.append(texto)
                ultimo_do_sistema = texto
            elif mensagens[-1]["role"] == "user":
                mensagens[-1]["notas"].append(nota)
            else:
                pendentes.append(nota)
            continue
        if papel not in ("user", "assistant"):
            continue
        blocos = _blocos_de(item.get("content"))
        if not blocos:
            continue
        if papel == "user" and pendentes:
            blocos = pendentes + blocos
            pendentes = []
        if mensagens and mensagens[-1]["role"] == papel:
            anterior = mensagens[-1]
            anterior["estavel"] = anterior["estavel"] + anterior["notas"] + blocos
            anterior["notas"] = []
        else:
            mensagens.append({"role": papel, "estavel": blocos, "notas": []})
    if pendentes:
        # Nota solta depois da fala do assistente: é um turno do usuário só de nota (sem parte estável),
        # para o ponto de cache ficar na fala do assistente e não na nota, que muda a cada pedido.
        mensagens.append({"role": "user", "estavel": [], "notas": pendentes})
    if not mensagens and ultimo_do_sistema is not None and sistema and sistema[-1] == ultimo_do_sistema:
        # Conversa sem nenhuma fala (primeiro papo de um canal): o último `developer` é a nota da vez, que muda
        # a cada pedido. Sozinha no `system` ela entraria no cache e o invalidaria sempre: vai para depois da
        # abertura, como a nota de qualquer outra conversa.
        sistema.pop()
        mensagens.append({"role": "user", "estavel": [{"type": "text", "text": ABERTURA}],
                          "notas": [{"type": "text", "text": ultimo_do_sistema}]})
    if not mensagens or mensagens[0]["role"] == "assistant":
        mensagens.insert(0, {"role": "user", "estavel": [{"type": "text", "text": ABERTURA}], "notas": []})
    if mensagens[-1]["role"] == "assistant":
        mensagens.append({"role": "user", "estavel": [{"type": "text", "text": CONTINUE}], "notas": []})

    saida = [{"role": m["role"], "content": m["estavel"] + m["notas"]} for m in mensagens]
    for i in range(len(mensagens) - 1, -1, -1):
        if mensagens[i]["estavel"]:
            ultimo = len(mensagens[i]["estavel"]) - 1
            saida[i]["content"][ultimo] = {**saida[i]["content"][ultimo], "cache_control": CACHE}
            break
    blocos_do_sistema = []
    if sistema:
        blocos_do_sistema = [{"type": "text", "text": "\n\n".join(sistema), "cache_control": CACHE}]
    return blocos_do_sistema, saida


# Palavras de JSON Schema que o Claude não aceita na saída estruturada (o resto o código do projeto confere).
_SEM_SUPORTE = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                "minLength", "maxLength", "maxItems", "uniqueItems", "minContains", "maxContains")


# Onde as chaves de um dicionário são NOMES (de propriedade, de definição) e não palavras do esquema, e onde os
# valores são dados do esquema e não esquemas.
_CHAVES_COM_NOMES = ("properties", "$defs", "definitions", "patternProperties")
_VALORES_LITERAIS = ("enum", "const", "default", "examples", "required")
# O que cada ramo de um `type` em lista leva consigo quando o tipo vira um `anyOf`.
_CAMPOS_DO_TIPO = {
    "string": ("format", "pattern"),
    "object": ("properties", "required", "additionalProperties", "patternProperties"),
    "array": ("items", "minItems", "prefixItems"),
}


def _tipo_json(valor) -> str:
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "boolean"
    if isinstance(valor, int):
        return "integer"
    if isinstance(valor, float):
        return "number"
    if isinstance(valor, str):
        return "string"
    return "object" if isinstance(valor, dict) else "array"


def _tipo_em_lista_para_anyof(no: dict) -> None:
    """`type: ["integer", "null"]` vira `anyOf` de um tipo cada. A documentação do Claude lista `anyOf`, mas não
    `type` em lista: o `anyOf` é equivalente e é o que sabemos que vale."""
    tipos = no.get("type")
    if not isinstance(tipos, list) or "anyOf" in no:
        return
    tipos = [t for t in tipos if isinstance(t, str)]
    if len(tipos) <= 1:
        if tipos:
            no["type"] = tipos[0]
        else:
            no.pop("type", None)
        return
    enum = no.pop("enum", None)
    ramos = []
    for tipo in tipos:
        ramo = {"type": tipo}
        for campo in _CAMPOS_DO_TIPO.get(tipo, ()):
            if campo in no:
                ramo[campo] = copy.deepcopy(no[campo])
        if enum is not None:
            valores = [v for v in enum if _tipo_json(v) == tipo or (tipo == "number" and _tipo_json(v) == "integer")]
            if valores and tipo != "null":
                ramo["enum"] = valores
            elif not valores:
                continue
        ramos.append(ramo)
    for tipo in tipos:
        for campo in _CAMPOS_DO_TIPO.get(tipo, ()):
            no.pop(campo, None)
    no.pop("type", None)
    if len(ramos) == 1:
        no.update(ramos[0])
    else:
        no["anyOf"] = ramos


def esquema_para_claude(esquema):
    """Cópia do esquema sem o que a saída estruturada do Claude recusa, com additionalProperties:false em todo objeto.

    Tira os limites que ele não aceita, troca `type` em lista por `anyOf` e não confunde NOME de propriedade com
    palavra do esquema (uma propriedade chamada `minimum` continua lá).
    """
    esquema = copy.deepcopy(esquema)

    def limpar(no):
        if isinstance(no, list):
            for item in no:
                limpar(item)
            return
        if not isinstance(no, dict):
            return
        for chave in _SEM_SUPORTE:
            no.pop(chave, None)
        if isinstance(no.get("minItems"), int) and no["minItems"] > 1:
            del no["minItems"]
        _tipo_em_lista_para_anyof(no)
        if no.get("type") == "object" or "properties" in no:
            no["additionalProperties"] = False
        for chave, valor in list(no.items()):
            if chave in _VALORES_LITERAIS:
                continue
            if chave in _CHAVES_COM_NOMES and isinstance(valor, dict):
                for filho in valor.values():
                    limpar(filho)
            else:
                limpar(valor)

    limpar(esquema)
    return esquema


def ferramentas_para_claude(ferramentas: list[dict] | None) -> list[dict]:
    """`tools` da Responses (type function, name, description, parameters) → `tools` do Claude (input_schema)."""
    saida = []
    for ferramenta in ferramentas or []:
        if not isinstance(ferramenta, dict) or ferramenta.get("type") != "function":
            continue
        saida.append({
            "name": ferramenta["name"],
            "description": ferramenta.get("description") or "",
            "input_schema": ferramenta.get("parameters") or {"type": "object", "properties": {}},
        })
    return saida


def corpo_claude(modelo: str, sistema: list[dict], mensagens: list[dict], esforco: str, max_saida: int,
                 esquema: dict | None = None, ferramentas: list[dict] | None = None,
                 usar_ferramentas: bool = True) -> dict:
    """O corpo do POST /v1/messages. `ferramentas` já vem no formato da OpenAI; `usar_ferramentas=False` manda `tool_choice: none`."""
    corpo = {"model": modelo, "max_tokens": max_saida, "messages": mensagens}
    if sistema:
        corpo["system"] = sistema
    extra = parametros_de_raciocinio(modelo, esforco)
    if "thinking" in extra:
        corpo["thinking"] = extra["thinking"]
    config = dict(extra.get("output_config") or {})
    if esquema is not None:
        config["format"] = {"type": "json_schema", "schema": esquema_para_claude(esquema)}
    if config:
        corpo["output_config"] = config
    tools = ferramentas_para_claude(ferramentas)
    if tools:
        corpo["tools"] = tools
        # tool_choice forçado (any/tool) dá 400 no Sonnet 5.5, Opus 5.5 e Fable 5.1: só auto ou none.
        corpo["tool_choice"] = {"type": "auto"} if usar_ferramentas else {"type": "none"}
    return corpo


# ── Resposta: formato do Claude → o que o resto do código lê ─────────────────


@dataclass
class RespostaClaude:
    texto: str
    parada: str
    blocos: list[dict] = field(default_factory=list)
    chamadas: list[dict] = field(default_factory=list)
    uso: dict | None = None
    detalhe: dict | None = None    # `stop_details` (a explicação da recusa, quando houve)


def uso_normalizado(uso: dict | None) -> dict | None:
    """`usage` do Claude no formato da OpenAI (input_tokens com o cache dentro), que o resto do código já lê."""
    if not uso:
        return None
    lido = int(uso.get("cache_read_input_tokens") or 0)
    escrito = int(uso.get("cache_creation_input_tokens") or 0)
    novo = int(uso.get("input_tokens") or 0)
    return {
        "input_tokens": novo + lido + escrito,
        "output_tokens": int(uso.get("output_tokens") or 0),
        "input_tokens_details": {"cached_tokens": lido, "cache_write_tokens": escrito},
    }


def ler_resposta_claude(dados: dict) -> RespostaClaude:
    """Lê os blocos pelo `type`, nunca pela posição: a resposta pode abrir com um bloco de pensamento."""
    blocos = [b for b in (dados.get("content") or []) if isinstance(b, dict)]
    texto = "".join(b.get("text") or "" for b in blocos if b.get("type") == "text").strip()
    chamadas = [b for b in blocos if b.get("type") == "tool_use"]
    detalhe = dados.get("stop_details")
    return RespostaClaude(texto=texto, parada=str(dados.get("stop_reason") or ""), blocos=blocos,
                          chamadas=chamadas, uso=uso_normalizado(dados.get("usage")),
                          detalhe=detalhe if isinstance(detalhe, dict) else None)
