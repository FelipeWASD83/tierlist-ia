"""Asks the AI to build a tier list. Claude (Messages) or OpenAI (Responses), over plain HTTP (urllib).

The model id decides the side (provedor.py). When one side runs out of credit, the same request is made
again with the pair model on the other side, and the empty side rests for 30 minutes (provedor.Disjuntor).

The model researches the theme with the provider's web search tool and hands the result back by calling
the `deliver_tierlist` tool, so the answer always arrives as JSON that matches the schema.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Callable

import provedor
from provedor import Disjuntor, eh_claude, provedor_de, reserva_de

URL_OPENAI = "https://api.openai.com/v1/responses"
URL_CLAUDE = "https://api.anthropic.com/v1/messages"
ATTEMPTS = 3
MAX_OUTPUT = 16000
MAX_ROUNDS = 6
WEB_SEARCH_PRICE = 10.0 / 1000      # US$ per search, both sides (official pricing pages, 2026-10)
DEFAULT_TIERS = ["S", "A", "B", "C", "D", "F"]

log = logging.getLogger(__name__)

# Models that take the web search variant with dynamic filtering. The rest use the basic one.
_NEW_WEB_SEARCH = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-5",
                   "claude-sonnet-4-6", "claude-fable-5")

TOOL_NAME = "deliver_tierlist"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short title for the tier list, in the language of the request."},
        "tiers": {
            "type": "array",
            "description": "The rows, best first. Usually S, A, B, C, D, F.",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string", "description": "Short row label, 1 to 12 characters."}},
                "required": ["label"],
                "additionalProperties": False,
            },
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "How the item is shown on the card. Short."},
                    "wikipedia_title": {"type": "string", "description":
                                        "Exact title of the item's own Wikipedia article (the one whose main "
                                        "image shows this item), or empty when there is none."},
                    "wikipedia_lang": {"type": "string", "description": "Language edition of that article: en, pt, ja..."},
                    "fandom_wiki": {"type": "string", "description":
                                    "For fiction (characters, weapons, bosses, places of a game, anime, series, "
                                    "comic, film): subdomain of the franchise's main Fandom wiki, e.g. 'onepiece' "
                                    "for onepiece.fandom.com. Empty otherwise."},
                    "fandom_title": {"type": "string", "description":
                                     "Exact title of the item's own article on that Fandom wiki, or empty."},
                    "image_query": {"type": "string", "description":
                                    "Image search query that finds a picture of exactly this item "
                                    "(add the franchise, brand or context so it is not ambiguous)."},
                },
                "required": ["name", "wikipedia_title", "wikipedia_lang", "fandom_wiki", "fandom_title", "image_query"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "tiers", "items"],
    "additionalProperties": False,
}
TOOL_DESCRIPTION = "Deliver the finished tier list. Call it exactly once, at the end, with every item."


class AIError(Exception):
    """Error with a message ready to show on screen."""


class NoCreditError(AIError):
    """One side (OpenAI or Claude) ran out of credit or hit its spending cap."""


_SIDES = {"openai": "OpenAI", "claude": "Claude"}


def system_prompt(count: int, web: bool) -> str:
    research = (
        "Use web search when the theme depends on recent or specific facts (releases, rosters, a "
        "season, a year) so the items are real and up to date. Do not search for images; "
        "searching once or twice is usually enough."
        if web else
        "Answer from what you already know."
    )
    return f"""You set up tier lists for a tier list app. The person describes a theme; you pick the items and hand everything back through the `{TOOL_NAME}` tool. The person ranks the items themselves, in the app: you never rank, judge or order them by quality, even when the request mentions a criterion ("strongest to weakest", "best to worst"). That criterion is for the person; use it only to choose which items belong in the list.

Rules:
- Exactly {count} items, unless the theme truly has fewer (then all of them). No duplicates.
- Items must be concrete things that have a picture: characters, games, foods, cars, songs, players, places...
- `name`: how a fan would label the card. Keep official proper names; translate generic things to the request's language.
- `wikipedia_title`: the exact title of the article about THIS item (a character's own article, not the series or a list of characters). Empty when no article is about it alone. Prefer English Wikipedia; use another edition only when the item has no English article.
- `fandom_wiki` and `fandom_title`: for anything from a game, anime, manga, series, comic or film, the franchise's main Fandom wiki (subdomain, e.g. `onepiece`, `naruto`, `eldenring`, `minecraft`) and the item's own article title there (Fandom often uses the full official name, e.g. "Trafalgar D. Water Law", "Kaidou"). Both empty for real-world things.
- `image_query`: a search query that finds this exact item's picture (e.g. "Monkey D. Luffy One Piece anime", "Hollow Knight game cover art").
- Rows: S, A, B, C, D, F by default. Use other labels only if the request asks for them or the theme clearly calls for it. The rows start empty.
- List the items in a neutral order (the theme's own order, like release or appearance, or alphabetical), never best to worst.
- {research}
- Title and row labels in the language of the request.
- When done, call `{TOOL_NAME}` once with the whole list. Do not write the list as text."""


def _web_search_tool(model: str) -> dict:
    name = model.lower()
    if name.startswith(_NEW_WEB_SEARCH):
        return {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    return {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def normalize(data: dict, count: int) -> dict:
    """Clean the tool input: valid rows, at most `count` items, no duplicates. Every item starts unranked
    (`tier` -1): even if a model sends a ranking anyway, it is dropped here."""
    if not isinstance(data, dict):
        raise AIError("A IA devolveu a tierlist num formato que não deu para ler.")
    tiers = []
    for tier in data.get("tiers") or []:
        label = str((tier or {}).get("label") or "").strip()[:24] if isinstance(tier, dict) else ""
        if label:
            tiers.append(label)
    tiers = tiers[:10] or list(DEFAULT_TIERS)
    seen = set()
    items = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        lang = str(item.get("wikipedia_lang") or "en").strip().lower()[:12]
        items.append({
            "name": name,
            "wikipedia_title": str(item.get("wikipedia_title") or "").strip()[:200],
            "wikipedia_lang": lang if lang.replace("-", "").isalpha() else "en",
            # the model sometimes writes the whole address: keep only the subdomain
            "fandom_wiki": str(item.get("fandom_wiki") or "").strip().lower().removeprefix("https://")
                .removeprefix("http://").split(".fandom.com")[0].split("/")[0][:60],
            "fandom_title": str(item.get("fandom_title") or "").strip()[:200],
            "image_query": str(item.get("image_query") or name).strip()[:200] or name,
            "tier": -1,
        })
        if len(items) >= count:
            break
    if not items:
        raise AIError("A IA não devolveu nenhum item. Tenta descrever a tierlist de outro jeito.")
    title = str(data.get("title") or "").strip()[:120] or "Tierlist"
    return {"title": title, "tiers": tiers, "items": items}


class AIClient:
    def __init__(self, model: str, effort: str = "medium", fallback: str = "auto", *,
                 claude_key: str = "", openai_key: str = "", url_claude: str = URL_CLAUDE,
                 url_openai: str = URL_OPENAI, timeout: float = 300, breaker: Disjuntor | None = None):
        self.model = model
        self.effort = effort
        self.fallback_setting = fallback
        self.claude_key = claude_key
        self.openai_key = openai_key
        self.url_claude = url_claude
        self.url_openai = url_openai
        self.timeout = timeout
        self.breaker = breaker or Disjuntor()

    # ── Which model answers ───────────────────────────────────────────────

    def has_key_for(self, model: str) -> bool:
        return bool(self.claude_key if eh_claude(model) else self.openai_key)

    def fallback(self) -> str | None:
        return reserva_de(self.model, self.fallback_setting)

    def order(self) -> list[str]:
        main, spare = self.model, self.fallback()
        candidates = [m for m in (main, spare) if m and self.has_key_for(m)]
        if len(candidates) == 2 and self.breaker.aberto(provedor_de(main)):
            candidates.reverse()
        return candidates

    # ── Public entry point ────────────────────────────────────────────────

    def build_tierlist(self, request: str, count: int, web: bool = True,
                       progress: Callable[[str], None] | None = None) -> dict:
        progress = progress or (lambda _text: None)
        order = self.order()
        if not order:
            raise AIError("Falta a chave da IA. Abra Configurações e cole a chave da Anthropic (ou da OpenAI).")
        failures: list[NoCreditError] = []
        for model in order:
            try:
                if eh_claude(model):
                    data, usage, searches = self._claude(model, request, count, web, progress)
                else:
                    data, usage, searches = self._openai(model, request, count, web, progress)
            except NoCreditError as e:
                self.breaker.abrir(provedor_de(model))
                failures.append(e)
                continue
            result = normalize(data, count)
            cost = provedor.custo(model, usage)
            if cost is not None:
                cost += searches * WEB_SEARCH_PRICE
            result.update({"model": model, "cost": cost, "searches": searches,
                           "replaced": model != self.model})
            return result
        if len(failures) == 1:
            spare = self.fallback()
            extra = (" Sem chave do outro lado para trocar." if spare and not self.has_key_for(spare)
                     else " Sem reserva configurada." if not spare else "")
            raise NoCreditError(f"{failures[0]}{extra}")
        raise NoCreditError("Os dois lados ficaram sem crédito. " + " ".join(str(f) for f in failures))

    # ── Claude ────────────────────────────────────────────────────────────

    def _claude(self, model, request, count, web, progress):
        system = [{"type": "text", "text": system_prompt(count, web), "cache_control": provedor.CACHE}]
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": request}]}]
        function = {"type": "function", "name": TOOL_NAME, "description": TOOL_DESCRIPTION, "parameters": TOOL_SCHEMA}
        usage_total = {"input_tokens": 0, "output_tokens": 0,
                       "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
        searches = 0
        nudged = False
        progress("Pesquisando o tema" if web else "Escolhendo os itens")
        for _round in range(MAX_ROUNDS):
            body = provedor.corpo_claude(model, system, messages, self.effort, MAX_OUTPUT, ferramentas=[function])
            body["tools"][0]["strict"] = True
            if web:
                body["tools"].append(_web_search_tool(model))
            data = self._post("claude", self.url_claude,
                              {"x-api-key": self.claude_key, "anthropic-version": provedor.ANTHROPIC_VERSAO}, body)
            usage = provedor.uso_normalizado(data.get("usage")) or {}
            _add_usage(usage_total, usage)
            searches += int(((data.get("usage") or {}).get("server_tool_use") or {}).get("web_search_requests") or 0)
            answer = provedor.ler_resposta_claude(data)
            for call in answer.chamadas:
                if call.get("name") == TOOL_NAME:
                    return call.get("input") or {}, usage_total, searches
            if answer.parada == "refusal":
                detail = (answer.detalhe or {}).get("explanation") or (answer.detalhe or {}).get("category") or "sem detalhe"
                raise AIError(f"O Claude ({model}) se recusou a montar essa tierlist: {detail}")
            if answer.parada == "max_tokens":
                raise AIError("A resposta da IA foi cortada no meio (max_tokens). Tenta com menos itens.")
            messages.append({"role": "assistant", "content": answer.blocos})
            if answer.parada == "pause_turn":
                progress("Ainda pesquisando")
                continue
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": [{"type": "text", "text":
                             f"Now call `{TOOL_NAME}` with the final list. Do not answer in text."}]})
            progress("Fechando a lista")
        raise AIError("A IA terminou sem entregar a tierlist. Tenta de novo ou descreve de outro jeito.")

    # ── OpenAI ────────────────────────────────────────────────────────────

    def _openai(self, model, request, count, web, progress):
        function = {"type": "function", "name": TOOL_NAME, "description": TOOL_DESCRIPTION,
                    "parameters": TOOL_SCHEMA, "strict": True}
        usage_total = {"input_tokens": 0, "output_tokens": 0,
                       "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
        searches = 0
        progress("Pesquisando o tema" if web else "Escolhendo os itens")
        for forced in (False, True):
            tools = [function] if forced or not web else [{"type": "web_search"}, function]
            body = {"model": model, "instructions": system_prompt(count, web), "input": request,
                    "tools": tools, "tool_choice": {"type": "function", "name": TOOL_NAME} if forced else "auto",
                    "reasoning": {"effort": self.effort}, "max_output_tokens": MAX_OUTPUT, "store": False}
            data = self._post("openai", self.url_openai, {"Authorization": f"Bearer {self.openai_key}"}, body)
            _add_usage(usage_total, data.get("usage") or {})
            for item in data.get("output") or []:
                if item.get("type") == "web_search_call":
                    searches += 1
                if item.get("type") == "function_call" and item.get("name") == TOOL_NAME:
                    try:
                        return json.loads(item.get("arguments") or "{}"), usage_total, searches
                    except ValueError as e:
                        raise AIError("O GPT devolveu a tierlist com JSON quebrado.") from e
            progress("Fechando a lista")
        raise AIError("O GPT terminou sem entregar a tierlist. Tenta de novo.")

    # ── Network ───────────────────────────────────────────────────────────

    def _post(self, side: str, url: str, headers: dict, body: dict) -> dict:
        name = _SIDES[side]
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(ATTEMPTS):
            last = attempt == ATTEMPTS - 1
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={**headers, "content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return _read_json(resp.read())
            except urllib.error.HTTPError as e:
                status = e.code
                data = _read_json(e.read())
                retry_after = e.headers.get("Retry-After") if e.headers else None
            except TimeoutError as e:
                raise AIError(f"O {name} demorou mais de {int(self.timeout)}s e eu desisti.") from e
            except urllib.error.URLError as e:
                if isinstance(e.reason, TimeoutError):
                    raise AIError(f"O {name} demorou mais de {int(self.timeout)}s e eu desisti.") from e
                # Never connected, so nothing was sent or charged: safe to try again.
                if not last:
                    time.sleep(2 ** attempt)
                    continue
                raise AIError(f"Não consegui conectar no {name}. A internet caiu?") from e
            except OSError as e:
                raise AIError(f"A conexão com o {name} caiu no meio: {e}") from e
            if provedor.falta_de_credito(status, data):
                raise NoCreditError(f"O {name} ficou sem crédito ({_detail(data)}).")
            if (status == 429 or status >= 500) and not last:
                time.sleep(_wait_seconds(retry_after, attempt))
                continue
            raise AIError(_error_message(name, status, data))
        raise AIError(f"Depois de três tentativas o {name} continuou sem responder.")


def _add_usage(total: dict, usage: dict) -> None:
    total["input_tokens"] += int(usage.get("input_tokens") or 0)
    total["output_tokens"] += int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    total["input_tokens_details"]["cached_tokens"] += int(details.get("cached_tokens") or 0)
    total["input_tokens_details"]["cache_write_tokens"] += int(details.get("cache_write_tokens") or 0)


def _read_json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _wait_seconds(retry_after, attempt: int) -> float:
    try:
        return min(30.0, max(0.0, float(retry_after)))
    except (TypeError, ValueError):
        return float(2 ** attempt)


def _detail(data: dict) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return error.get("message") or "sem detalhe"
    return str(error or "sem detalhe")


def _error_message(name: str, status: int, data: dict) -> str:
    detail = _detail(data)
    if status == 401:
        return f"O {name} recusou a chave (401). Confere a chave em Configurações."
    if status == 429:
        return f"O {name} limitou os pedidos (429): {detail}"
    if status == 404:
        return f"O {name} não achou o modelo (404): {detail}"
    if status == 529:
        return f"O {name} está sobrecarregado agora (529). Tenta daqui a pouco."
    return f"O {name} respondeu erro {status}: {detail}"
