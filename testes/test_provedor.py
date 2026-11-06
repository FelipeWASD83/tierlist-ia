"""provedor.py: o que a OpenAI e o Claude têm em comum, sem rede.

Este teste é IGUAL nos projetos Python que têm o provedor.py; só a linha de import muda.
"""

import copy
import unittest

import provedor  # noqa: E402
from provedor import (ABERTURA, CONTINUE, Disjuntor, converter_entrada, corpo_claude, custo, eh_claude,
                              esquema_para_claude, falta_de_credito, ferramentas_para_claude, ler_resposta_claude,
                              parametros_de_raciocinio, provedor_de, reserva_de, uso_normalizado)

CREDITO_OPENAI = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.",
                            "type": "insufficient_quota", "code": "insufficient_quota"}}
CREDITO_CLAUDE = {"type": "error", "error": {"type": "invalid_request_error", "message":
                  "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}


class TestLado(unittest.TestCase):
    def test_o_id_decide_o_lado(self):
        for modelo in ("claude-haiku-5-5", "claude-sonnet-5-5", "Claude-Opus-5-5", "claude-opus-4-8"):
            self.assertTrue(eh_claude(modelo), modelo)
            self.assertEqual(provedor_de(modelo), "claude")
        for modelo in ("gpt-6-luna", "gpt-6.1-sol", "o3", "ft:gpt-6-luna:org::id", "", None):
            self.assertFalse(eh_claude(modelo), modelo)
            self.assertEqual(provedor_de(modelo), "openai")


class TestReserva(unittest.TestCase):
    def test_pares_da_tabela(self):
        self.assertEqual(reserva_de("gpt-6-luna"), "claude-haiku-5-5")
        self.assertEqual(reserva_de("claude-haiku-5-5"), "gpt-6-luna")
        self.assertEqual(reserva_de("gpt-6.1-sol"), "claude-sonnet-5-5")
        self.assertEqual(reserva_de("claude-sonnet-5-5"), "gpt-6.1-sol")
        self.assertEqual(reserva_de("gpt-6-astra"), "claude-opus-5-5")
        self.assertEqual(reserva_de("claude-opus-5-5"), "gpt-6-astra")

    def test_modelo_fora_da_tabela_cai_no_barato_do_outro_lado(self):
        self.assertEqual(reserva_de("gpt-9-qualquer"), "claude-haiku-5-5")
        self.assertEqual(reserva_de("claude-inventado-9"), "gpt-6-luna")

    def test_id_escolhido_tem_que_ser_do_outro_lado(self):
        self.assertEqual(reserva_de("gpt-6-luna", "claude-opus-5-5"), "claude-opus-5-5")
        self.assertEqual(reserva_de("claude-haiku-5-5", "gpt-6-sol"), "gpt-6-sol")
        # Do mesmo lado não serve: acabou o crédito do lado, acabou para os dois.
        self.assertEqual(reserva_de("gpt-6-luna", "gpt-6-sol"), "claude-haiku-5-5")

    def test_id_com_data_no_fim_acha_o_par_do_modelo_sem_data(self):
        self.assertEqual(reserva_de("claude-sonnet-5-5-20260101"), "gpt-6.1-sol")
        self.assertEqual(reserva_de("claude-haiku-5-5-20260101"), "gpt-6-luna")

    def test_pares_dos_modelos_que_nao_sao_os_cinco_principais(self):
        for claude, gpt in (("claude-opus-5", "gpt-6-astra"), ("claude-sonnet-5", "gpt-6.1-sol"), ("claude-fable-5", "gpt-6-astra"),
                            ("claude-opus-4-8", "gpt-6-astra"), ("claude-sonnet-4-6", "gpt-6.1-sol"), ("claude-haiku-4-5", "gpt-6-luna")):
            self.assertEqual(reserva_de(claude), gpt, claude)
        self.assertEqual(reserva_de("gpt-5.6-luna"), "claude-haiku-5-5")
        self.assertEqual(reserva_de("gpt-5.6-sol"), "claude-sonnet-5-5")

    def test_desligar_a_reserva(self):
        for valor in ("nenhuma", "Nenhuma", "off", "não"):
            self.assertIsNone(reserva_de("gpt-6-luna", valor), valor)

    def test_vazio_e_auto_sao_a_mesma_coisa(self):
        self.assertEqual(reserva_de("gpt-6-luna", ""), "claude-haiku-5-5")
        self.assertEqual(reserva_de("gpt-6-luna", None), "claude-haiku-5-5")


class TestSemCredito(unittest.TestCase):
    def test_reconhece_os_dois_lados(self):
        self.assertTrue(falta_de_credito(429, CREDITO_OPENAI))
        self.assertTrue(falta_de_credito(400, CREDITO_CLAUDE))
        self.assertTrue(falta_de_credito(402, {}))
        self.assertTrue(falta_de_credito(402, None))
        self.assertTrue(falta_de_credito(402, {"type": "error", "error": {"type": "billing_error", "message": "x"}}))

    def test_conta_da_openai_sem_cobranca_ativa_vem_como_401(self):
        dados = {"error": {"code": "billing_not_active", "type": "billing_not_active",
                           "message": "Your account is not active, please check your billing details on our website."}}
        self.assertTrue(falta_de_credito(401, dados))
        self.assertFalse(falta_de_credito(401, {"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}}))

    def test_teto_de_gasto_da_organizacao(self):
        dados = {"type": "error", "error": {"type": "invalid_request_error", "message":
                 "You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC."}}
        self.assertTrue(falta_de_credito(400, dados))
        self.assertTrue(falta_de_credito(400, {"error": {"code": "billing_hard_limit_reached", "message": "x"}}))

    def test_o_que_nao_e_falta_de_credito(self):
        limite = {"error": {"message": "Rate limit reached for gpt-6-luna on tokens per min (TPM).",
                            "type": "tokens", "code": "rate_limit_exceeded"}}
        self.assertFalse(falta_de_credito(429, limite))
        self.assertFalse(falta_de_credito(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}))
        self.assertFalse(falta_de_credito(401, {"error": {"message": "invalid api key"}}))
        self.assertFalse(falta_de_credito(500, {"error": {"message": "pane"}}))
        self.assertFalse(falta_de_credito(529, {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}))
        self.assertFalse(falta_de_credito(400, {"error": {"message": "max_tokens must be positive"}}))
        self.assertFalse(falta_de_credito(404, CREDITO_CLAUDE))   # só os status que a API usa para isso
        self.assertFalse(falta_de_credito(400, None))
        self.assertFalse(falta_de_credito(400, {"error": "texto solto"}))

    def test_mensagem_de_credito_com_o_status_errado_nao_conta_fora_dos_status_certos(self):
        self.assertFalse(falta_de_credito(200, CREDITO_OPENAI))
        self.assertFalse(falta_de_credito(500, CREDITO_CLAUDE))


class TestDisjuntor(unittest.TestCase):
    def setUp(self):
        self.agora = [1000.0]
        self.d = Disjuntor(segundos=1800, relogio=lambda: self.agora[0])

    def test_aberto_ate_passar_o_prazo(self):
        self.assertFalse(self.d.aberto("openai"))
        self.d.abrir("openai")
        self.assertTrue(self.d.aberto("openai"))
        self.assertFalse(self.d.aberto("claude"))
        self.agora[0] += 1799
        self.assertTrue(self.d.aberto("openai"))
        self.agora[0] += 2
        self.assertFalse(self.d.aberto("openai"))
        self.assertEqual(self.d.minutos_restantes("openai"), 0)

    def test_minutos_restantes_arredonda_para_cima(self):
        self.d.abrir("claude")
        self.assertEqual(self.d.minutos_restantes("claude"), 30)
        self.agora[0] += 1790
        self.assertEqual(self.d.minutos_restantes("claude"), 1)

    def test_duas_threads_vencendo_o_prazo_juntas_nao_dao_erro(self):
        import threading
        barreira = threading.Barrier(2, timeout=5)
        prender = [False]

        def relogio():
            # Com `prender` ligado, as duas threads param aqui, entre o get e a remoção, e seguem juntas.
            if prender[0]:
                barreira.wait()
            return self.agora[0]

        d = Disjuntor(segundos=1800, relogio=relogio)
        d.abrir("openai")
        self.agora[0] += 3600
        prender[0] = True
        erros = []

        def consultar():
            try:
                d.aberto("openai")
            except Exception as e:   # noqa: BLE001 - o teste existe para pegar qualquer erro
                erros.append(e)

        fios = [threading.Thread(target=consultar) for _ in range(2)]
        for f in fios:
            f.start()
        for f in fios:
            f.join(10)
        self.assertEqual(erros, [])

    def test_aberto_depois_do_prazo_nao_levanta_nem_com_chamadas_seguidas(self):
        self.d.abrir("openai")
        self.agora[0] += 1801
        self.assertFalse(self.d.aberto("openai"))
        self.assertFalse(self.d.aberto("openai"))

    def test_fechar(self):
        self.d.abrir("openai")
        self.d.fechar("openai")
        self.assertFalse(self.d.aberto("openai"))
        self.d.fechar("openai")   # fechar o que não está aberto não dá erro


class TestRaciocinio(unittest.TestCase):
    def test_sem_pensar(self):
        self.assertEqual(parametros_de_raciocinio("claude-haiku-5-5", "none"), {"thinking": {"type": "disabled"}})
        # O Sonnet 5.5 recusa o disabled com 400 e desliga com between_tools, sem mais nada dentro de thinking.
        self.assertEqual(parametros_de_raciocinio("claude-sonnet-5-5", "none"),
                         {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}})
        # O Opus 5.5 e o Fable não desligam o pensamento: vão no esforço mais baixo.
        self.assertEqual(parametros_de_raciocinio("claude-opus-5-5", "none"), {"output_config": {"effort": "low"}})
        self.assertEqual(parametros_de_raciocinio("claude-fable-5-1", "none"), {"output_config": {"effort": "low"}})

    def test_pensando(self):
        esperado = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}}
        for modelo in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-opus-5"):
            self.assertEqual(parametros_de_raciocinio(modelo, "medium"), esperado, modelo)

    def test_xhigh_so_onde_existe(self):
        self.assertEqual(parametros_de_raciocinio("claude-opus-5-5", "xhigh")["output_config"], {"effort": "xhigh"})
        self.assertEqual(parametros_de_raciocinio("claude-sonnet-4-6", "xhigh")["output_config"], {"effort": "high"})

    def test_modelo_antigo_nao_recebe_esforco_nem_pensamento(self):
        for modelo in ("claude-haiku-4-5", "claude-haiku-4-5-20251001", "claude-sonnet-4-5", "claude-opus-4-5"):
            self.assertEqual(parametros_de_raciocinio(modelo, "high"), {}, modelo)
            self.assertEqual(parametros_de_raciocinio(modelo, "none"), {}, modelo)

    def test_esforco_estranho_vira_low(self):
        self.assertEqual(parametros_de_raciocinio("claude-haiku-5-5", "turbo")["output_config"], {"effort": "low"})


class TestConverterEntrada(unittest.TestCase):
    def test_instrucoes_viram_system_e_a_hora_vai_depois_do_cache(self):
        sistema, mensagens = converter_entrada("Seja breve.", [
            {"role": "user", "content": "oi"},
            {"role": "developer", "content": "Agora é segunda-feira."},
        ])
        self.assertEqual(sistema, [{"type": "text", "text": "Seja breve.", "cache_control": provedor.CACHE}])
        self.assertEqual(mensagens, [{"role": "user", "content": [
            {"type": "text", "text": "oi", "cache_control": provedor.CACHE},
            {"type": "text", "text": "Agora é segunda-feira."},
        ]}])

    def test_historico_alterna_e_o_cache_fica_na_ultima_fala_dele(self):
        _, mensagens = converter_entrada("", [
            {"role": "user", "content": "um"},
            {"role": "assistant", "content": "dois"},
            {"role": "user", "content": "três"},
            {"role": "developer", "content": "nota"},
        ])
        self.assertEqual([m["role"] for m in mensagens], ["user", "assistant", "user"])
        self.assertNotIn("cache_control", mensagens[0]["content"][0])
        self.assertEqual(mensagens[2]["content"][0]["cache_control"], provedor.CACHE)
        self.assertNotIn("cache_control", mensagens[2]["content"][1])
        self.assertEqual(sum("cache_control" in b for m in mensagens for b in m["content"]), 1)

    def test_nota_depois_da_fala_do_assistente_fica_depois_do_cache(self):
        # O pedido do servidor-ia: a ficha no começo, o histórico do canal (as falas do próprio como assistant)
        # e a nota da vez no fim. Se a última fala é do assistente, o cache não pode cair na nota (ela muda sempre).
        sistema, mensagens = converter_entrada("", [
            {"role": "developer", "content": "ficha"},
            {"role": "user", "content": "um"},
            {"role": "assistant", "content": "dois"},
            {"role": "developer", "content": "nota da vez"},
        ])
        self.assertEqual(sistema[0]["text"], "ficha")
        self.assertEqual([m["role"] for m in mensagens], ["user", "assistant", "user"])
        self.assertEqual(mensagens[1]["content"], [{"type": "text", "text": "dois", "cache_control": provedor.CACHE}])
        self.assertEqual(mensagens[2]["content"], [{"type": "text", "text": "nota da vez"}])
        self.assertEqual(sum("cache_control" in b for m in mensagens for b in m["content"]), 1)

    def test_nota_sozinha_depois_do_assistente_com_abertura(self):
        # Histórico que começa pelo assistente: entra a abertura, e o cache continua na fala dele, antes da nota.
        _, mensagens = converter_entrada("", [{"role": "assistant", "content": "oi, sou eu"},
                                              {"role": "developer", "content": "nota"}])
        self.assertEqual([m["role"] for m in mensagens], ["user", "assistant", "user"])
        self.assertEqual(mensagens[0]["content"][0]["text"], ABERTURA)
        self.assertIn("cache_control", mensagens[1]["content"][0])
        self.assertEqual(mensagens[2]["content"], [{"type": "text", "text": "nota"}])

    def test_developer_do_comeco_vai_para_o_system(self):
        sistema, mensagens = converter_entrada("Personagem.", [
            {"role": "developer", "content": "Memória."},
            {"role": "system", "content": "Regras."},
            {"role": "user", "content": "oi"},
        ])
        self.assertEqual(sistema[0]["text"], "Personagem.\n\nMemória.\n\nRegras.")
        self.assertEqual(len(mensagens), 1)

    def test_developer_depois_do_assistente_espera_a_proxima_fala_dele(self):
        _, mensagens = converter_entrada("", [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "developer", "content": "nota do meio"},
            {"role": "user", "content": "c"},
        ])
        self.assertEqual([b["text"] for b in mensagens[2]["content"]], ["nota do meio", "c"])

    def test_claude_nao_aceita_comecar_nem_terminar_pelo_assistente(self):
        _, mensagens = converter_entrada("", [{"role": "assistant", "content": "oi, sou eu"}])
        self.assertEqual([m["role"] for m in mensagens], ["user", "assistant", "user"])
        self.assertEqual(mensagens[0]["content"][0]["text"], ABERTURA)
        self.assertEqual(mensagens[2]["content"][0]["text"], CONTINUE)

    def test_canal_sem_fala_nenhuma_nao_poe_a_nota_da_vez_no_cache(self):
        sistema, mensagens = converter_entrada("Personagem.", [
            {"role": "developer", "content": "Servidor em volta."},
            {"role": "developer", "content": "Agora é segunda, 14:05. Puxe assunto."},
        ])
        self.assertEqual(sistema[0]["text"], "Personagem.\n\nServidor em volta.")
        self.assertNotIn("14:05", sistema[0]["text"])
        self.assertEqual(len(mensagens), 1)
        self.assertEqual(mensagens[0]["content"][0]["text"], ABERTURA)
        self.assertIn("cache_control", mensagens[0]["content"][0])
        self.assertEqual(mensagens[0]["content"][1], {"type": "text", "text": "Agora é segunda, 14:05. Puxe assunto."})

    def test_entrada_vazia_ainda_tem_uma_mensagem(self):
        for entrada in ([], "", None, [{"role": "user", "content": "   "}]):
            _, mensagens = converter_entrada("regra", entrada)
            self.assertEqual(len(mensagens), 1, entrada)
            self.assertEqual(mensagens[0]["role"], "user")

    def test_texto_solto(self):
        _, mensagens = converter_entrada("", "traduza isto")
        self.assertEqual(mensagens[0]["content"][0]["text"], "traduza isto")

    def test_mesmo_papel_seguido_vira_uma_mensagem(self):
        _, mensagens = converter_entrada("", [
            {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "d"},
        ])
        self.assertEqual([b["text"] for b in mensagens[0]["content"]], ["a", "b"])
        self.assertEqual(len(mensagens), 3)

    def test_partes_e_imagens(self):
        _, mensagens = converter_entrada("", [{"role": "user", "content": [
            {"type": "input_text", "text": "olha"},
            {"type": "input_image", "image_url": "data:image/png;base64,QUJD", "detail": "low"},
            {"type": "input_image", "image_url": "https://exemplo.com/a.jpg"},
            {"type": "input_image", "image_url": "ftp://nao"},
        ]}])
        blocos = mensagens[0]["content"]
        self.assertEqual(blocos[0]["text"], "olha")
        self.assertEqual(blocos[1], {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}})
        self.assertEqual(blocos[2]["source"], {"type": "url", "url": "https://exemplo.com/a.jpg"})
        self.assertEqual(len(blocos), 3)
        self.assertIn("cache_control", blocos[2])

    def test_campos_que_so_a_openai_conhece_somem(self):
        _, mensagens = converter_entrada("", [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b", "phase": "final_answer"},
            {"role": "user", "content": "c"},
            {"type": "reasoning", "summary": []},
        ])
        self.assertEqual(len(mensagens), 3)
        self.assertNotIn("phase", mensagens[1])

    def test_nao_mexe_na_entrada(self):
        entrada = [{"role": "user", "content": [{"type": "input_image", "image_url": "data:image/png;base64,QUJD"}]},
                   {"role": "developer", "content": "nota"}]
        copia = copy.deepcopy(entrada)
        converter_entrada("regra", entrada)
        self.assertEqual(entrada, copia)

    def test_so_um_ponto_de_cache_nas_mensagens_e_um_no_system(self):
        sistema, mensagens = converter_entrada("regra", [{"role": "user", "content": "a"},
                                                         {"role": "assistant", "content": "b"},
                                                         {"role": "user", "content": "c"}])
        marcas = sum("cache_control" in b for m in mensagens for b in m["content"]) + sum("cache_control" in b for b in sistema)
        self.assertEqual(marcas, 2)   # o limite do Claude é 4


class TestEsquemaEFerramentas(unittest.TestCase):
    def test_tira_o_que_o_claude_recusa_e_garante_additional_properties(self):
        esquema = {"type": "object", "required": ["n", "itens"], "properties": {
            "n": {"type": "integer", "minimum": 0, "maximum": 10},
            "texto": {"type": "string", "minLength": 1, "maxLength": 40},
            "itens": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "object", "properties": {"a": {"type": "string"}}}},
        }}
        copia = copy.deepcopy(esquema)
        saida = esquema_para_claude(esquema)
        self.assertEqual(esquema, copia)
        self.assertNotIn("minimum", saida["properties"]["n"])
        self.assertNotIn("maxLength", saida["properties"]["texto"])
        self.assertNotIn("minItems", saida["properties"]["itens"])
        self.assertNotIn("maxItems", saida["properties"]["itens"])
        self.assertIs(saida["additionalProperties"], False)
        self.assertIs(saida["properties"]["itens"]["items"]["additionalProperties"], False)
        self.assertEqual(saida["required"], ["n", "itens"])

    def test_propriedade_chamada_como_palavra_do_esquema_continua_la(self):
        esquema = {"type": "object", "required": ["minimum", "maxLength"], "properties": {
            "minimum": {"type": "integer", "minimum": 0}, "maxLength": {"type": "string", "maxLength": 9}}}
        saida = esquema_para_claude(esquema)
        self.assertEqual(set(saida["properties"]), {"minimum", "maxLength"})
        self.assertNotIn("minimum", saida["properties"]["minimum"])
        self.assertNotIn("maxLength", saida["properties"]["maxLength"])
        self.assertEqual(saida["required"], ["minimum", "maxLength"])

    def test_type_em_lista_vira_anyof(self):
        esquema = {"type": "object", "required": ["n", "t", "o"], "properties": {
            "n": {"type": ["integer", "null"]},
            "t": {"type": ["string", "null"], "enum": ["a", "b", None], "description": "x"},
            "o": {"type": ["object", "null"], "properties": {"a": {"type": ["string", "null"]}}, "required": ["a"]},
            "u": {"type": ["string"]}, "v": {"type": []}}}
        copia = copy.deepcopy(esquema)
        saida = esquema_para_claude(esquema)
        self.assertEqual(esquema, copia)
        p = saida["properties"]
        self.assertEqual(p["n"], {"anyOf": [{"type": "integer"}, {"type": "null"}]})
        self.assertEqual(p["t"], {"description": "x", "anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]})
        self.assertEqual(p["o"]["anyOf"][0]["type"], "object")
        self.assertIs(p["o"]["anyOf"][0]["additionalProperties"], False)
        self.assertEqual(p["o"]["anyOf"][0]["properties"]["a"], {"anyOf": [{"type": "string"}, {"type": "null"}]})
        self.assertEqual(p["o"]["anyOf"][0]["required"], ["a"])
        self.assertEqual(p["o"]["anyOf"][1], {"type": "null"})
        self.assertEqual(p["u"], {"type": "string"})
        self.assertNotIn("type", p["v"])

    def test_type_em_lista_com_enum_sem_valor_do_tipo_descarta_o_ramo(self):
        saida = esquema_para_claude({"type": ["string", "integer"], "enum": ["a", "b"]})
        self.assertEqual(saida, {"type": "string", "enum": ["a", "b"]})

    def test_min_items_um_ou_zero_fica(self):
        saida = esquema_para_claude({"type": "array", "minItems": 1, "items": {"type": "string"}})
        self.assertEqual(saida["minItems"], 1)

    def test_ferramentas(self):
        ferramentas = [{"type": "function", "name": "apagar", "description": "apaga", "strict": True,
                        "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}}},
                       {"type": "web_search"}]
        self.assertEqual(ferramentas_para_claude(ferramentas), [
            {"name": "apagar", "description": "apaga",
             "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}}}])
        self.assertEqual(ferramentas_para_claude(None), [])


class TestCorpo(unittest.TestCase):
    def test_corpo_simples_sem_temperatura(self):
        sistema, mensagens = converter_entrada("regra", [{"role": "user", "content": "oi"}])
        corpo = corpo_claude("claude-haiku-5-5", sistema, mensagens, "low", 4000)
        self.assertEqual(corpo["model"], "claude-haiku-5-5")
        self.assertEqual(corpo["max_tokens"], 4000)
        self.assertEqual(corpo["thinking"], {"type": "adaptive"})
        self.assertEqual(corpo["output_config"], {"effort": "low"})
        for proibido in ("temperature", "top_p", "top_k", "tools", "tool_choice"):
            self.assertNotIn(proibido, corpo)

    def test_saida_estruturada(self):
        sistema, mensagens = converter_entrada("", "x")
        esquema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
        corpo = corpo_claude("claude-sonnet-5-5", sistema, mensagens, "none", 1000, esquema=esquema)
        self.assertEqual(corpo["output_config"]["format"], {"type": "json_schema", "schema": esquema})
        self.assertEqual(corpo["output_config"]["effort"], "low")
        self.assertEqual(corpo["thinking"], {"type": "between_tools"})

    def test_ferramentas_so_com_auto_ou_none(self):
        sistema, mensagens = converter_entrada("", "x")
        ferramentas = [{"type": "function", "name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}]
        com = corpo_claude("claude-opus-5-5", sistema, mensagens, "low", 1000, ferramentas=ferramentas)
        self.assertEqual(com["tool_choice"], {"type": "auto"})
        sem = corpo_claude("claude-opus-5-5", sistema, mensagens, "low", 1000, ferramentas=ferramentas, usar_ferramentas=False)
        self.assertEqual(sem["tool_choice"], {"type": "none"})


class TestRespostaECusto(unittest.TestCase):
    def test_le_os_blocos_pelo_tipo(self):
        dados = {"stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": "olá"}, {"type": "text", "text": " mundo"},
            {"type": "tool_use", "id": "tu_1", "name": "f", "input": {"a": 1}}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 800, "cache_creation_input_tokens": 50, "output_tokens": 30}}
        r = ler_resposta_claude(dados)
        self.assertEqual(r.texto, "olá mundo")
        self.assertEqual(r.parada, "end_turn")
        self.assertEqual(r.chamadas[0]["name"], "f")
        self.assertEqual(r.uso, {"input_tokens": 950, "output_tokens": 30,
                                 "input_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 50}})

    def test_guarda_a_explicacao_da_recusa(self):
        r = ler_resposta_claude({"stop_reason": "refusal", "content": [],
                                 "stop_details": {"type": "refusal", "category": "cyber", "explanation": "não posso"}})
        self.assertEqual(r.parada, "refusal")
        self.assertEqual(r.detalhe["explanation"], "não posso")
        self.assertIsNone(ler_resposta_claude({"stop_details": "texto"}).detalhe)
        self.assertIsNone(ler_resposta_claude({}).detalhe)

    def test_preco_dos_gpt_5_que_o_seletor_ainda_lista(self):
        self.assertIsNotNone(custo("gpt-5-mini", {"input_tokens": 1000, "output_tokens": 10}))
        self.assertIsNotNone(custo("gpt-5-nano", {"input_tokens": 1000, "output_tokens": 10}))

    def test_resposta_vazia(self):
        r = ler_resposta_claude({})
        self.assertEqual((r.texto, r.parada, r.chamadas, r.uso), ("", "", [], None))
        self.assertIsNone(uso_normalizado(None))

    def test_custo_com_cache(self):
        uso = {"input_tokens": 10_000, "output_tokens": 1_000, "input_tokens_details": {"cached_tokens": 8_000, "cache_write_tokens": 500}}
        # 1.500 cheios a 2,00 + 8.000 de cache a 0,10 + 500 gravados a 2,50 + 1.000 de saída a 10,00 (por milhão)
        self.assertAlmostEqual(custo("claude-sonnet-5-5", uso), (1500 * 2 + 8000 * 0.10 + 500 * 2.5 + 1000 * 10) / 1e6)

    def test_custo_de_modelo_desconhecido(self):
        self.assertIsNone(custo("claude-inventado-9", {"input_tokens": 1}))
        self.assertIsNone(custo("gpt-6-luna", None))
        self.assertIsNotNone(custo("claude-haiku-4-5-20251001", {"input_tokens": 1000, "output_tokens": 10}))


if __name__ == "__main__":
    unittest.main()
