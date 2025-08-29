# ai_nlq_ai.py
"""
NLQ (perguntas livres) para 'chamados' com fallback seguro.
- Com OPENAI_API_KEY: usa a API da OpenAI para interpretar a pergunta (parser -> JSON) e para "free_summary".
- Sem chave: roteador por palavras-chave cobre intents comuns (oldest_open, 48h, por UBS, etc.).

Exporta:
  - answer_question(chamados: list, question: str) -> dict
  - ia_available() -> bool
"""

import os, json, re, unicodedata
from typing import Any, Dict, Optional
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

# OpenAI é OPCIONAL — o módulo funciona sem ela (só limita recursos "IA")
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

FORTALEZA_TZ = pytz.timezone("America/Fortaleza")
MODEL = "gpt-4o-mini"  # ajustar se quiser outro

# ---------------- OpenAI helpers ----------------
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
    if OpenAI is None:
        return None
    api_key = _get_openai_api_key()
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

_CLIENT = _make_openai_client()

def _has_openai() -> bool:
    return _CLIENT is not None


# --------------- Parser via IA (JSON controlado) ---------------
_PARSER_SYSTEM = (
    "Você converte perguntas em português sobre chamados de TI em JSON com o schema:\n"
    '{ "intent":"list_open|oldest_open|count_open|open_by_ubs|open_over_hours|'
    'top_defects|avg_resolution|open_in_ubs|search_text|free_summary",'
    '  "filters":{"ubs":"","setor":"","contains":""}, "hours":48 }\n'
    "- 'open_over_hours' deve trazer 'hours' (int) quando solicitado, ex: 24, 48, 72.\n"
    "- 'search_text' usa filters.contains.\n"
    "- Se mencionar UBS/setor, preencher filters.ubs/filters.setor com o texto citado.\n"
    "NÃO gere SQL. Retorne SOMENTE JSON puro, sem comentários."
)

# --------- helpers de normalização e fuzzy ---------
def _norm_txt(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())

def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_norm_txt(a).split()), set(_norm_txt(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0

def _resolve_best_match(target: str, catalog: list[str]) -> Optional[str]:
    """Match por normalização + startswith + Jaccard (leve)."""
    if not target or not catalog:
        return None
    tnorm = _norm_txt(target)

    norm_map = { _norm_txt(c): c for c in catalog }
    if tnorm in norm_map:
        return norm_map[tnorm]

    starts = [norm_map[k] for k in norm_map.keys() if k.startswith(tnorm)]
    if len(starts) == 1:
        return starts[0]
    elif len(starts) > 1:
        return sorted(starts, key=lambda x: len(str(x)), reverse=True)[0]

    best, best_score = None, 0.0
    for c in catalog:
        sc = _jaccard(target, str(c))
        if sc > best_score:
            best, best_score = c, sc
    return best if best_score >= 0.34 else None  # limiar leve


# --------- roteador por palavras-chave (funciona sem IA) ---------
def _keyword_router(question: str) -> Dict[str, Any] | None:
    q = _norm_txt(question)

    if any(k in q for k in ["mais antigo", "antigo", "velho"]):
        return {"intent": "oldest_open", "filters": {}}
    if any(k in q for k in ["quantos abertos", "qtd abertos", "numero de abertos", "quantidade de abertos"]):
        return {"intent": "count_open", "filters": {}}
    if any(k in q for k in ["48h", "48 h", "acima de 48", "mais de 48"]):
        return {"intent": "open_over_hours", "filters": {}, "hours": 48}
    if any(k in q for k in ["72h", "72 h", "acima de 72", "mais de 72"]):
        return {"intent": "open_over_hours", "filters": {}, "hours": 72}
    if any(k in q for k in ["por ubs", "ubs com mais", "mais chamados por ubs"]):
        return {"intent": "open_by_ubs", "filters": {}}
    if any(k in q for k in ["tipos de defeito", "defeitos comuns", "mais comuns"]):
        return {"intent": "top_defects", "filters": {}}
    if any(k in q for k in ["tempo medio", "tempo médio", "sla medio", "sla médio"]):
        return {"intent": "avg_resolution", "filters": {}}

    # “na UBS X” (pega o que vem depois de 'ubs'/'unidade'/'sede')
    m = re.search(r"(ubs|unidade|sede)\s+([a-z0-9\s\-\._/]+)", q)
    if m:
        nome = m.group(2).strip()
        return {"intent": "open_in_ubs", "filters": {"ubs": nome}}

    # “buscar ...” / “procurar ...” / “contém ...”
    m2 = re.search(r"(buscar|procurar|contem|contém)\s+(.+)", q)
    if m2:
        termo = m2.group(2).strip()
        return {"intent": "search_text", "filters": {"contains": termo}}

    # “resumo”
    if "resumo" in q or "sumario" in q or "sumário" in q:
        return {"intent": "free_summary", "filters": {}}

    return None


# --------- extração robusta de JSON vindo da IA ---------
def _extract_json_block(text: str) -> Optional[str]:
    """
    Extrai o primeiro bloco {...} mesmo se vier entre ```json ... ```
    """
    try:
        start = text.index("{")
        end = text.rindex("}")
        blob = text[start:end+1]
        blob = re.sub(r"```.*?```", "", blob, flags=re.S)  # remove blocos markdown
        return blob
    except Exception:
        return None


def _parse_question_llm(question: str) -> Dict[str, Any]:
    """
    Usa IA para transformar a pergunta em JSON; com fallback para roteador e intents padrão.
    """
    # 0) roteador manual (funciona sem IA)
    routed = _keyword_router(question)
    if routed:
        return routed

    # 1) sem IA -> fallback
    if not _has_openai():
        return {"intent": "list_open", "filters": {}}

    # 2) tenta IA
    try:
        r = _CLIENT.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": _PARSER_SYSTEM},
                {"role": "user", "content": f"Pergunta: {question}\nRetorne apenas JSON, sem texto extra."}
            ],
            temperature=0.1,
        )
        content = (r.choices[0].message.content or "").strip()
        blob = _extract_json_block(content) or content
        data = json.loads(blob)

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

    except Exception as e:
        print("Falha no parse IA:", e)
        return {"intent": "list_open", "filters": {}}


# ----------------- Helpers de dados -----------------
def _prepare_df(chamados: list) -> pd.DataFrame:
    df = pd.DataFrame(chamados).copy()
    if df.empty:
        return df
    df["abertura_dt"] = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["fechamento_dt"] = pd.to_datetime(df["hora_fechamento"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["em_aberto"] = df["fechamento_dt"].isna()
    return df


def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """
    Filtra usando APENAS o catálogo real do banco (sem aliases).
    - UBS/Setor: normaliza e tenta best-match; se não bater, usa contains.
    """
    if df.empty:
        return df

    ubs = (filters.get("ubs") or "").strip()
    setor = (filters.get("setor") or "").strip()
    contains = (filters.get("contains") or "").strip()

    # UBS
    if ubs and "ubs" in df.columns:
        catalog = sorted([str(x) for x in df["ubs"].dropna().unique().tolist()], key=lambda x: x)
        resolved = _resolve_best_match(ubs, catalog)
        if resolved:
            df = df[df["ubs"] == resolved]
        else:
            df = df[df["ubs"].astype(str).str.upper().str.contains(ubs.upper(), na=False)]

    # Setor
    if setor and "setor" in df.columns:
        cat_setor = sorted([str(x) for x in df["setor"].dropna().unique().tolist()], key=lambda x: x)
        resolved_setor = _resolve_best_match(setor, cat_setor)
        if resolved_setor:
            df = df[df["setor"] == resolved_setor]
        else:
            df = df[df["setor"].astype(str).str.upper().str.contains(setor.upper(), na=False)]

    # Texto livre no problema
    if contains and "problema" in df.columns:
        df = df[df["problema"].astype(str).str.upper().str.contains(contains.upper(), na=False)]

    return df


def _calc_horas_uteis(abertura_str: str, fim_dt: datetime) -> float:
    """
    Usa calculate_working_hours se existir; senão, aproxima por horas corridas.
    """
    try:
        from chamados import calculate_working_hours
        ab = datetime.strptime(abertura_str, "%d/%m/%Y %H:%M:%S")
        delta = calculate_working_hours(ab, fim_dt)
        return round(delta.total_seconds() / 3600.0, 2)
    except Exception:
        try:
            ab = datetime.strptime(abertura_str, "%d/%m/%Y %H:%M:%S")
            return round((fim_dt - ab).total_seconds() / 3600.0, 2)
        except Exception:
            return np.nan


# ----------------- Executor principal -----------------
def answer_question(chamados: list, question: str) -> Dict[str, Any]:
    """
    Executa a pergunta NLQ contra os 'chamados'.

    Retorna:
      { "ok": bool, "markdown": str, "table": pd.DataFrame | None }
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

    # legenda de filtros interpretados
    inte = []
    if filters.get("ubs"):   inte.append(f"UBS='{filters['ubs']}'")
    if filters.get("setor"): inte.append(f"Setor='{filters['setor']}'")
    filtro_txt = " | " + ", ".join(inte) if inte else ""

    # list_open
    if intent == "list_open":
        res = df_f[df_f["em_aberto"]]
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum chamado em aberto para este filtro.{filtro_txt}", "table": None}
        cols = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura"] if c in res.columns]
        tbl = res[cols].sort_values("hora_abertura", ascending=True) if cols else res.sort_values("hora_abertura", ascending=True)
        return {"ok": True, "markdown": f"**Abertos**: {len(res)}{filtro_txt}", "table": tbl}

    # oldest_open
    if intent == "oldest_open":
        res = df_f[df_f["em_aberto"]].dropna(subset=["abertura_dt"])
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum chamado em aberto.{filtro_txt}", "table": None}
        row = res.sort_values("abertura_dt", ascending=True).iloc[0]
        md = (
            f"**Mais antigo (aberto):** protocolo **{row.get('protocolo','N/A')}** — "
            f"{row.get('hora_abertura','N/A')} — **{row.get('ubs','N/A')}** / **{row.get('setor','N/A')}**{filtro_txt}\n\n"
            f"*{row.get('problema','(sem descrição)')}*"
        )
        return {"ok": True, "markdown": md, "table": None}

    # count_open
    if intent == "count_open":
        q = int(df_f["em_aberto"].sum())
        return {"ok": True, "markdown": f"**Chamados em aberto:** **{q}**{filtro_txt}", "table": None}

    # open_by_ubs
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
            return {"ok": True, "markdown": f"Nenhum chamado em aberto.{filtro_txt}", "table": None}
        return {"ok": True, "markdown": f"**Abertos por UBS:**{filtro_txt}", "table": res}

    # open_over_hours
    if intent == "open_over_hours":
        hours = int(parsed.get("hours", 48))
        now_local = datetime.now(FORTALEZA_TZ)
        df_op = df_f[df_f["em_aberto"]].copy()
        if df_op.empty:
            return {"ok": True, "markdown": f"Nenhum chamado em aberto.{filtro_txt}", "table": None}
        df_op["idade_uteis_h"] = df_op.apply(lambda r: _calc_horas_uteis(r.get("hora_abertura",""), now_local), axis=1)
        res = df_op[df_op["idade_uteis_h"] > hours].copy()
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum aberto acima de **{hours}h úteis**.{filtro_txt}", "table": None}
        cols = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura","idade_uteis_h"] if c in res.columns]
        res = res[cols].sort_values("idade_uteis_h", ascending=False) if cols else res.sort_values("idade_uteis_h", ascending=False)
        return {"ok": True, "markdown": f"**Abertos acima de {hours}h úteis:** **{len(res)}**{filtro_txt}", "table": res}

    # top_defects
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
            return {"ok": True, "markdown": f"Sem dados para o filtro.{filtro_txt}", "table": None}
        return {"ok": True, "markdown": f"**Tipos de defeito mais comuns (top):**{filtro_txt}", "table": top}

    # avg_resolution
    if intent == "avg_resolution":
        fechados = df_f[~df_f["em_aberto"]].copy()
        if fechados.empty:
            return {"ok": True, "markdown": f"Nenhum chamado fechado no filtro.{filtro_txt}", "table": None}
        try:
            from chamados import calculate_working_hours
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
                return {"ok": True, "markdown": f"Não foi possível calcular.{filtro_txt}", "table": None}
            horas = round(v.mean() / 3600.0, 1)
            return {"ok": True, "markdown": f"**Tempo médio de resolução (horas úteis):** **{horas} h**.{filtro_txt}", "table": None}
        except Exception:
            return {"ok": True, "markdown": f"Cálculo de horas úteis indisponível.{filtro_txt}", "table": None}

    # open_in_ubs
    if intent == "open_in_ubs":
        alvo = (filters.get("ubs") or "").strip()
        if not alvo:
            return {"ok": False, "markdown": "Qual UBS? Ex: 'abertos na SEDE I'.", "table": None}
        res = df_f[df_f["em_aberto"]]
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum chamado em aberto.{filtro_txt}", "table": None}
        cols = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura"] if c in res.columns]
        return {"ok": True, "markdown": f"**Abertos na UBS (interpretação): {len(res)}**{filtro_txt}", "table": res[cols] if cols else res}

    # search_text
    if intent == "search_text":
        text = (filters.get("contains") or "").strip()
        if not text:
            return {"ok": False, "markdown": "Diga o que procurar. Ex: 'buscar toner', 'procurar não liga'", "table": None}
        res = df_f[df_f["problema"].astype(str).str.upper().str.contains(text.upper(), na=False)]
        if res.empty:
            return {"ok": True, "markdown": f"Nenhum chamado contendo '{text}'.{filtro_txt}", "table": None}
        cols = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura","hora_fechamento"] if c in res.columns]
        return {"ok": True, "markdown": f"**Encontrados:** {len(res)} contendo '{text}'{filtro_txt}", "table": res[cols].head(200) if cols else res.head(200)}

    # free_summary
    if intent == "free_summary":
        if not _has_openai():
            return {"ok": False, "markdown": "⚠️ Resumo IA indisponível: configure OPENAI_API_KEY.", "table": None}
        cols = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura","hora_fechamento"] if c in df_f.columns]
        base = df_f[cols].head(300) if cols else df_f.head(300)
        csv_chunk = base.to_csv(index=False)
        prompt = (
            "Você é um analista de suporte. Faça um resumo executivo em 6-10 bullets do CSV de chamados (máx 300 linhas):\n"
            "- volume por UBS e por setor\n- principais tipos de defeito\n- riscos (abertos antigos)\n- próximas ações objetivas\n\nCSV:\n" + csv_chunk
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

    # fallback
    return {"ok": False, "markdown": "Não entendi. Tente: 'abertos por ubs', 'acima de 48h', 'tipos de defeito mais comuns'.", "table": None}


# -------- status público da IA --------
def ia_available() -> bool:
    return _has_openai()