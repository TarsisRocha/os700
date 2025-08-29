import os
import json
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import pytz

# OpenAI opcional: o módulo funciona mesmo sem a chave (apenas intents "free_summary" e o parsing IA ficam limitados)
try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

# =========================
# OpenAI - inicialização segura
# =========================
def _get_openai_api_key() -> Optional[str]:
    # 1) env var
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    # 2) streamlit secrets (opcional)
    try:
        import streamlit as st  # type: ignore
        if "openai" in st.secrets and "api_key" in st.secrets["openai"]:
            return st.secrets["openai"]["api_key"]
    except Exception:
        pass
    return None

def _make_openai_client() -> Optional["OpenAI"]:
    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

_CLIENT = _make_openai_client()
MODEL = "gpt-4o-mini"  # rápido/viável para parsing e resumos; ajuste se preferir

def _has_openai() -> bool:
    return _CLIENT is not None


# =========================
# Parsing IA da pergunta -> JSON controlado
# =========================
_PARSER_SYSTEM = (
    "Você é um parser que converte perguntas em português sobre 'chamados' de TI "
    "em um JSON com o seguinte schema. NUNCA crie campos fora disso e NÃO gere SQL.\n\n"
    "Schema JSON:\n"
    "{\n"
    '  "intent": "list_open | oldest_open | count_open | open_by_ubs | open_over_hours | '
    'top_defects | avg_resolution | open_in_ubs | search_text | free_summary",\n'
    '  "filters": {"ubs": "<string|opcional>", "setor": "<string|opcional>", "contains": "<string|opcional>"},\n'
    '  "hours": <int|opcional para open_over_hours>\n'
    "}\n\n"
    "- Se a pergunta pedir apenas um resumo narrativo, use intent=free_summary.\n"
    "- Se falar 'acima de 72h', 'acima de 24h', etc., use open_over_hours com 'hours' correspondente.\n"
    "- Se pedir 'buscar', 'procurar', 'contém', use search_text com filters.contains.\n"
    "- Se mencionar uma UBS específica, preencha filters.ubs com o texto capturado (sem normalizar demais).\n"
    "- Se mencionar setor, preencha filters.setor.\n"
    "- Retorne APENAS JSON puro, sem comentários nem texto extra."
)

def _parse_question_llm(question: str) -> Dict[str, Any]:
    """
    Tenta usar LLM para mapear pergunta -> JSON controlado.
    Fallback: retorna list_open sem filtros.
    """
    if not _has_openai():
        # Sem OpenAI: fallback seguro
        return {"intent": "list_open", "filters": {}}

    try:
        r = _CLIENT.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": _PARSER_SYSTEM},
                {"role": "user", "content": f"Pergunta: {question}\nRetorne somente JSON."}
            ],
            temperature=0.1,
        )
        content = r.choices[0].message.content.strip()
        data = json.loads(content)

        # sane defaults
        if not isinstance(data, dict):
            raise ValueError("Resposta do parser não é JSON objeto.")

        data.setdefault("intent", "list_open")
        data.setdefault("filters", {})
        if not isinstance(data["filters"], dict):
            data["filters"] = {}

        if data.get("intent") == "open_over_hours":
            try:
                data["hours"] = int(data.get("hours", 48))
            except Exception:
                data["hours"] = 48

        return data
    except Exception:
        # Fallback total
        return {"intent": "list_open", "filters": {}}


# =========================
# Helpers de negócio
# =========================
def _prepare_df(chamados: list) -> pd.DataFrame:
    df = pd.DataFrame(chamados).copy()
    if df.empty:
        return df
    df["abertura_dt"] = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["fechamento_dt"] = pd.to_datetime(df["hora_fechamento"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["em_aberto"] = df["fechamento_dt"].isna()
    return df

def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df
    ubs = (filters.get("ubs") or "").strip()
    setor = (filters.get("setor") or "").strip()
    contains = (filters.get("contains") or "").strip()

    if ubs:
        df = df[df["ubs"].astype(str).str.upper().str.contains(ubs.upper(), na=False)]
    if setor:
        df = df[df["setor"].astype(str).str.upper().str.contains(setor.upper(), na=False)]
    if contains:
        df = df[df["problema"].astype(str).str.upper().str.contains(contains.upper(), na=False)]
    return df

def _calc_horas_uteis(abertura_str: str, fim_dt: datetime) -> float:
    """
    Usa calculate_working_hours se existir; caso contrário, aproxima por horas corridas.
    """
    try:
        from chamados import calculate_working_hours  # import tardio para evitar dependência cíclica
        ab = datetime.strptime(abertura_str, "%d/%m/%Y %H:%M:%S")
        delta = calculate_working_hours(ab, fim_dt)
        return round(delta.total_seconds() / 3600.0, 2)
    except Exception:
        try:
            ab = datetime.strptime(abertura_str, "%d/%m/%Y %H:%M:%S")
            return round((fim_dt - ab).total_seconds() / 3600.0, 2)
        except Exception:
            return np.nan


# =========================
# Execução dos intents
# =========================
def answer_question(chamados: list, question: str) -> Dict[str, Any]:
    """
    Processa a pergunta 'question' contra os dados 'chamados' (lista de dicts).

    Retorno:
      {
        "ok": True/False,
        "markdown": "texto pronto para exibir",
        "table": pd.DataFrame | None
      }
    """
    if not chamados:
        return {"ok": False, "markdown": "Sem dados de chamados.", "table": None}

    df = _prepare_df(chamados)
    if df.empty:
        return {"ok": False, "markdown": "Sem dados de chamados.", "table": None}

    parsed = _parse_question_llm(question)
    intent = parsed.get("intent", "list_open")
    filters = parsed.get("filters", {})
    df_f = _apply_filters(df, filters)

    # ---------- list_open ----------
    if intent == "list_open":
        res = df_f[df_f["em_aberto"]]
        if res.empty:
            return {"ok": True, "markdown": "Nenhum chamado em aberto para este filtro.", "table": None}
        cols = [c for c in ["protocolo", "ubs", "setor", "tipo_defeito", "problema", "hora_abertura"] if c in res.columns]
        return {
            "ok": True,
            "markdown": f"**Abertos**: {len(res)}",
            "table": res[cols].sort_values("hora_abertura", ascending=True) if cols else res.sort_values("hora_abertura")
        }

    # ---------- oldest_open ----------
    if intent == "oldest_open":
        res = df_f[df_f["em_aberto"]].dropna(subset=["abertura_dt"])
        if res.empty:
            return {"ok": True, "markdown": "Nenhum chamado em aberto.", "table": None}
        row = res.sort_values("abertura_dt", ascending=True).iloc[0]
        md = (
            f"**Mais antigo (aberto):** protocolo **{row.get('protocolo','N/A')}** — "
            f"{row.get('hora_abertura','N/A')} — **{row.get('ubs','N/A')}** / **{row.get('setor','N/A')}**\n\n"
            f"*{row.get('problema','(sem descrição)')}*"
        )
        return {"ok": True, "markdown": md, "table": None}

    # ---------- count_open ----------
    if intent == "count_open":
        q = int(df_f["em_aberto"].sum())
        return {"ok": True, "markdown": f"**Chamados em aberto:** **{q}**", "table": None}

    # ---------- open_by_ubs ----------
    if intent == "open_by_ubs":
        if "ubs" not in df_f.columns:
            return {"ok": False, "markdown": "Coluna 'ubs' não encontrada.", "table": None}
        res = (
            df_f[df_f["em_aberto"]]
            .groupby("ubs")
            .size()
            .reset_index(name="abertos")
            .sort_values("abertos", ascending=False)
        )
        if res.empty:
            return {"ok": True, "markdown": "Nenhum chamado em aberto.", "table": None}
        return {"ok": True, "markdown": "**Abertos por UBS:**", "table": res}

    # ---------- open_over_hours ----------
    if intent == "open_over_hours":
        hours = int(parsed.get("hours", 48))
        now_local = datetime.now(FORTALEZA_TZ)
        df_op = df_f[df_f["em_aberto"]].copy()
        if df_op.empty:
            return {"ok": True, "markdown": "Nenhum chamado em aberto.", "table": None}
        df_op["idade_uteis_h"] = df_op.apply(
            lambda r: _calc_horas_uteis(r.get("hora_abertura", ""), now_local), axis=1
        )
        res = df_op[df_op["idade_uteis_h"] > hours].copy()
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum aberto acima de **{hours}h úteis**.", "table": None}
        cols = [c for c in ["protocolo", "ubs", "setor", "tipo_defeito", "problema", "hora_abertura", "idade_uteis_h"] if c in res.columns]
        res = res[cols].sort_values("idade_uteis_h", ascending=False) if cols else res.sort_values("idade_uteis_h", ascending=False)
        return {"ok": True, "markdown": f"**Abertos acima de {hours}h úteis:** **{len(res)}**", "table": res}

    # ---------- top_defects ----------
    if intent == "top_defects":
        if "tipo_defeito" not in df_f.columns:
            return {"ok": False, "markdown": "Coluna 'tipo_defeito' não encontrada.", "table": None}
        top = (
            df_f.groupby("tipo_defeito")
            .size()
            .reset_index(name="qtd")
            .sort_values("qtd", ascending=False)
            .head(15)
        )
        if top.empty:
            return {"ok": True, "markdown": "Sem dados para o filtro.", "table": None}
        return {"ok": True, "markdown": "**Tipos de defeito mais comuns (top):**", "table": top}

    # ---------- avg_resolution ----------
    if intent == "avg_resolution":
        fechados = df_f[~df_f["em_aberto"]].copy()
        if fechados.empty:
            return {"ok": True, "markdown": "Nenhum chamado fechado no filtro.", "table": None}
        try:
            from chamados import calculate_working_hours  # import tardio
            def _t(row):
                try:
                    ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
                    fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
                    return calculate_working_hours(ab, fe).total_seconds()
                except Exception:
                    return np.nan
            fechados["t_resolucao_seg"] = fechados.apply(_t, axis=1)
            v = fechados["t_resolucao_seg"].dropna()
            if v.empty:
                return {"ok": True, "markdown": "Não foi possível calcular.", "table": None}
            horas = round(v.mean() / 3600, 1)
            return {"ok": True, "markdown": f"**Tempo médio de resolução (horas úteis):** **{horas} h**.", "table": None}
        except Exception:
            return {"ok": True, "markdown": "Cálculo de horas úteis indisponível.", "table": None}

    # ---------- open_in_ubs ----------
    if intent == "open_in_ubs":
        alvo = (filters.get("ubs") or "").strip()
        if not alvo:
            return {"ok": False, "markdown": "Qual UBS? Ex: 'abertos na SEDE I'.", "table": None}
        res = df_f[df_f["em_aberto"] & df_f["ubs"].astype(str).str.upper().str.contains(alvo.upper(), na=False)]
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum aberto na UBS '{alvo}'.", "table": None}
        cols = [c for c in ["protocolo", "setor", "tipo_defeito", "problema", "hora_abertura"] if c in res.columns]
        return {"ok": True, "markdown": f"**Abertos na UBS '{alvo}': {len(res)}**", "table": res[cols] if cols else res}

    # ---------- search_text ----------
    if intent == "search_text":
        text = (filters.get("contains") or "").strip()
        if not text:
            return {"ok": False, "markdown": "Diga o que procurar. Ex: 'buscar toner', 'procurar não liga'", "table": None}
        res = df_f[df_f["problema"].astype(str).str.upper().str.contains(text.upper(), na=False)]
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum chamado contendo '{text}'.", "table": None}
        cols = [c for c in ["protocolo", "ubs", "setor", "tipo_defeito", "problema", "hora_abertura", "hora_fechamento"] if c in res.columns]
        return {"ok": True, "markdown": f"**Encontrados:** {len(res)} contendo '{text}'", "table": res[cols].head(200) if cols else res.head(200)}

    # ---------- free_summary ----------
    if intent == "free_summary":
        if not _has_openai():
            return {"ok": False, "markdown": "⚠️ Resumo IA indisponível: configure OPENAI_API_KEY.", "table": None}
        cols = [c for c in ["protocolo", "ubs", "setor", "tipo_defeito", "problema", "hora_abertura", "hora_fechamento"] if c in df_f.columns]
        base = df_f[cols].head(300) if cols else df_f.head(300)
        csv_chunk = base.to_csv(index=False)
        prompt = (
            "Você é um analista de suporte. Faça um resumo executivo em 6-10 bullets do CSV de chamados (máx 300 linhas):\n"
            "- destaques de volume por UBS e por setor\n"
            "- principais tipos de defeito\n"
            "- risco (abertos mais antigos)\n"
            "- sugestões objetivas de próxima ação\n\n"
            f"CSV:\n{csv_chunk}"
        )
        try:
            r = _CLIENT.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return {"ok": True, "markdown": r.choices[0].message.content, "table": None}
        except Exception:
            return {"ok": False, "markdown": "Falha ao gerar resumo IA.", "table": None}

    # ---------- fallback ----------
    return {"ok": False, "markdown": "Não entendi. Tente reformular ou pergunte algo como: 'abertos por ubs', 'acima de 48h', 'tipos de defeito mais comuns'.", "table": None}