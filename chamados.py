import os
import streamlit as st
from supabase_client import supabase
from datetime import datetime, timedelta
import pytz
from twilio.rest import Client

# Define o fuso de Fortaleza
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

# =======================================================
# WhatsApp (Twilio)
# =======================================================
def send_whatsapp_message(message_body):
    """
    Envia a mensagem de WhatsApp para cada técnico listado na variável de ambiente
    TECHNICIAN_WHATSAPP_NUMBER (números separados por vírgula).
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
    technician_numbers = os.getenv("TECHNICIAN_WHATSAPP_NUMBER", "")
    
    if not all([account_sid, auth_token, from_whatsapp_number, technician_numbers]):
        # Evita quebrar o fluxo se as variáveis não estiverem definidas no ambiente
        return
    
    numbers_list = [num.strip() for num in technician_numbers.split(",") if num.strip()]
    
    try:
        client = Client(account_sid, auth_token)
    except Exception as e:
        st.error(f"Erro ao iniciar cliente Twilio: {e}")
        return

    for number in numbers_list:
        to_whatsapp_number = number if number.startswith("whatsapp:") else f"whatsapp:{number}"
        try:
            client.messages.create(
                body=message_body,
                from_=from_whatsapp_number,
                to=to_whatsapp_number
            )
        except Exception as e:
            st.error(f"Erro ao enviar mensagem para {to_whatsapp_number}: {e}")

# =======================================================
# Protocolo sequencial
# =======================================================
def gerar_protocolo_sequencial():
    try:
        resp = supabase.table("chamados").select("protocolo").execute()
        protocolos = [int(item["protocolo"]) for item in resp.data if item.get("protocolo") not in (None, "")] if resp.data else []
        return (max(protocolos) + 1) if protocolos else 1
    except Exception as e:
        st.error(f"Erro ao gerar protocolo: {e}")
        return None

# =======================================================
# Buscas básicas
# =======================================================
def get_chamado_by_protocolo(protocolo):
    try:
        resp = supabase.table("chamados").select("*").eq("protocolo", protocolo).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        st.error(f"Erro ao buscar chamado: {e}")
        return None

def buscar_no_inventario_por_patrimonio(patrimonio):
    try:
        resp = supabase.table("inventario").select("*").eq("numero_patrimonio", patrimonio).execute()
        if resp.data:
            machine = resp.data[0]
            return {
                "tipo": machine.get("tipo"),
                "marca": machine.get("marca"),
                "modelo": machine.get("modelo"),
                "patrimonio": machine.get("numero_patrimonio"),
                "localizacao": machine.get("localizacao"),
                "setor": machine.get("setor")
            }
        return None
    except Exception as e:
        st.error(f"Erro ao buscar patrimônio: {e}")
        return None

# =======================================================
# Criação / atualização de chamado
# =======================================================
def add_chamado(username, ubs, setor, tipo_defeito, problema, machine=None, patrimonio=None):
    """
    Cria um chamado no Supabase, definindo a hora de abertura em Fortaleza (UTC−3)
    e — se possível — envia uma mensagem via WhatsApp para os técnicos.
    """
    try:
        protocolo = gerar_protocolo_sequencial()
        if protocolo is None:
            return None

        hora_local = datetime.now(FORTALEZA_TZ).strftime('%d/%m/%Y %H:%M:%S')

        data = {
            "username": username,
            "ubs": ubs,
            "setor": setor,
            "tipo_defeito": tipo_defeito,
            "problema": problema,
            "hora_abertura": hora_local,
            "protocolo": protocolo,
            "machine": machine,
            "patrimonio": patrimonio,
            # novos campos de status (opcionalmente nulos na criação)
            "status_chamado": None,
            "peca_necessaria": None,
            "tecnico_responsavel": None,
        }
        supabase.table("chamados").insert(data).execute()
        
        # WhatsApp (não bloqueia o fluxo se falhar)
        try:
            message_body = f"Novo chamado aberto: Protocolo {protocolo}. UBS: {ubs}. Problema: {tipo_defeito}"
            send_whatsapp_message(message_body)
        except Exception:
            pass
        
        st.success("Chamado aberto com sucesso!")
        return protocolo
    except Exception as e:
        st.error(f"Erro ao adicionar chamado: {e}")
        return None

def atualizar_status_chamado(id_chamado, status_chamado=None, peca_necessaria=None, tecnico_responsavel=None):
    """
    Atualiza campos de status do chamado:
      - status_chamado: ex. 'Aguardando Peça' (ou None para limpar)
      - peca_necessaria: texto da peça (ou None)
      - tecnico_responsavel: nome (ou None)

    Se as colunas não existirem na tabela, mostre o SQL de criação no log/erro.
    """
    try:
        payload = {
            "status_chamado": status_chamado,
            "peca_necessaria": peca_necessaria,
            "tecnico_responsavel": tecnico_responsavel
        }
        supabase.table("chamados").update(payload).eq("id", id_chamado).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar status do chamado: {e}")
        st.info("Se a tabela não possuir as colunas de status, crie com:")
        st.code(
            "ALTER TABLE public.chamados "
            "ADD COLUMN IF NOT EXISTS status_chamado text, "
            "ADD COLUMN IF NOT EXISTS peca_necessaria text, "
            "ADD COLUMN IF NOT EXISTS tecnico_responsavel text;",
            language="sql"
        )
        return False

def marcar_aguardando_peca(id_chamado, peca=None, tecnico=None):
    """
    Atalho para marcar o chamado como 'Aguardando Peça'.
    """
    return atualizar_status_chamado(
        id_chamado,
        status_chamado="Aguardando Peça",
        peca_necessaria=(peca or None),
        tecnico_responsavel=(tecnico or None),
    )

def limpar_status_aguardando(id_chamado):
    """
    Remove status 'Aguardando Peça' (limpa os campos relacionados).
    """
    return atualizar_status_chamado(
        id_chamado,
        status_chamado=None,
        peca_necessaria=None,
        tecnico_responsavel=None,
    )

def finalizar_chamado(id_chamado, solucao, pecas_usadas=None):
    """
    Finaliza um chamado, definindo a hora de fechamento em Fortaleza (UTC−3).
    Também insere as peças usadas e registra histórico de manutenção.
    Ao finalizar, limpamos status_chamado/peca_necessaria/tecnico_responsavel.
    """
    try:
        hora_fechamento_local = datetime.now(FORTALEZA_TZ).strftime('%d/%m/%Y %H:%M:%S')

        supabase.table("chamados").update({
            "solucao": solucao,
            "hora_fechamento": hora_fechamento_local,
            "status_chamado": None,
            "peca_necessaria": None,
            "tecnico_responsavel": None,
        }).eq("id", id_chamado).execute()
        
        # Entrada de peças (se na UI não veio nada, pode perguntar; mas por padrão vem da tela)
        if pecas_usadas is None:
            pecas_input = st.text_area("Informe as peças utilizadas (separadas por vírgula)")
            pecas_usadas = [p.strip() for p in pecas_input.split(",") if p.strip()] if pecas_input else []
        
        if pecas_usadas:
            for peca in pecas_usadas:
                supabase.table("pecas_usadas").insert({
                    "chamado_id": id_chamado,
                    "peca_nome": peca,
                    "data_uso": hora_fechamento_local
                }).execute()
                # baixa no estoque
                try:
                    from estoque import dar_baixa_estoque
                    dar_baixa_estoque(peca, quantidade_usada=1)
                except Exception:
                    pass
        
        # histórico por patrimônio (se houver)
        resp = supabase.table("chamados").select("patrimonio").eq("id", id_chamado).execute()
        patrimonio = resp.data[0].get("patrimonio") if (resp.data and len(resp.data) > 0) else None

        if patrimonio:
            descricao = f"Manutenção: {solucao}. Peças utilizadas: {', '.join(pecas_usadas) if pecas_usadas else 'Nenhuma'}."
            supabase.table("historico_manutencao").insert({
                "numero_patrimonio": patrimonio,
                "descricao": descricao,
                "data_manutencao": hora_fechamento_local
            }).execute()
        
        st.success(f"Chamado {id_chamado} finalizado.")
    except Exception as e:
        st.error(f"Erro ao finalizar chamado: {e}")

# =======================================================
# Listagens
# =======================================================
def list_chamados():
    """
    Retorna todos os chamados da tabela 'chamados'.
    """
    try:
        resp = supabase.table("chamados").select("*").execute()
        return resp.data or []
    except Exception as e:
        st.error(f"Erro ao listar chamados: {e}")
        return []

def list_chamados_em_aberto():
    """
    Retorna todos os chamados onde hora_fechamento IS NULL.
    """
    try:
        resp = supabase.table("chamados").select("*").is_("hora_fechamento", None).execute()
        return resp.data or []
    except Exception as e:
        st.error(f"Erro ao listar chamados abertos: {e}")
        return []

def get_chamados_por_patrimonio(patrimonio):
    """
    Retorna todos os chamados vinculados a um patrimônio específico.
    """
    try:
        resp = supabase.table("chamados").select("*").eq("patrimonio", patrimonio).execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error(f"Erro ao buscar chamados para o patrimônio {patrimonio}: {e}")
        return []

# =======================================================
# Horas úteis
# =======================================================
def calculate_working_hours(start, end):
    """
    Calcula o tempo útil entre 'start' e 'end', considerando o expediente:
      - Manhã: 08:00 a 12:00
      - Tarde: 13:00 a 17:00
    Ignora sábados e domingos.
    Retorna um objeto timedelta com o tempo útil.
    """
    if start >= end:
        return timedelta(0)
    
    total_seconds = 0
    current = start

    while current < end:
        # Sábado (5) ou domingo (6): pula para o próximo dia
        if current.weekday() >= 5:
            current = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
            continue

        morning_start = current.replace(hour=8, minute=0, second=0, microsecond=0)
        morning_end   = current.replace(hour=12, minute=0, second=0, microsecond=0)
        afternoon_start = current.replace(hour=13, minute=0, second=0, microsecond=0)
        afternoon_end   = current.replace(hour=17, minute=0, second=0, microsecond=0)

        if end > morning_start:
            interval_start = max(current, morning_start)
            interval_end = min(end, morning_end)
            if interval_end > interval_start:
                total_seconds += (interval_end - interval_start).total_seconds()
        
        if end > afternoon_start:
            interval_start = max(current, afternoon_start)
            interval_end = min(end, afternoon_end)
            if interval_end > interval_start:
                total_seconds += (interval_end - interval_start).total_seconds()
        
        current = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
    
    return timedelta(seconds=total_seconds)

# =======================================================
# Reabrir chamado
# =======================================================
def reabrir_chamado(id_chamado, remover_historico=False):
    """
    Reabre um chamado que foi finalizado, removendo hora_fechamento e solucao.
    Se remover_historico=True, também apaga o registro de manutenção
    referente à data de fechamento anterior (se quiser).
    """
    try:
        resp = supabase.table("chamados").select("*").eq("id", id_chamado).execute()
        if not resp.data:
            st.error("Chamado não encontrado.")
            return
        chamado = resp.data[0]

        if not chamado.get("hora_fechamento"):
            st.info("Chamado já está em aberto.")
            return

        old_hora_fechamento = chamado["hora_fechamento"]
        patrimonio = chamado.get("patrimonio")

        supabase.table("chamados").update({
            "hora_fechamento": None,
            "solucao": None
        }).eq("id", id_chamado).execute()

        if remover_historico and patrimonio and old_hora_fechamento:
            supabase.table("historico_manutencao").delete() \
                .eq("numero_patrimonio", patrimonio) \
                .eq("data_manutencao", old_hora_fechamento) \
                .execute()

        st.success(f"Chamado {id_chamado} reaberto com sucesso!")
    except Exception as e:
        st.error(f"Erro ao reabrir chamado: {e}")