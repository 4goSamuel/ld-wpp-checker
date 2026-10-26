"""
LD WhatsApp Checker
Abre as instâncias do LDPlayer de N em N, abre o WhatsApp, verifica se o número
está banido e, se estiver, fecha e exclui a instância. No final mostra um
relatório e salva em relatorio_ld.txt (mesma pasta do script/exe).

Requisitos: Windows + LDPlayer 9 + Python 3.8+ (sem bibliotecas extras).
Uso: python ld_wpp_checker.py   (ou rodar.bat / LD_WPP_Checker.exe)
"""

import datetime
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# ======================= CONFIGURAÇÕES =======================
LDCONSOLE = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"   # ajuste se instalou em outro lugar
LOTE = 2                       # quantos LDs verificar ao mesmo tempo
PULAR_INDICES = [0]            # instâncias que nunca devem ser tocadas (0 = principal)
SO_NOMES_COM_NUMERO = True     # True = só verifica instâncias cujo nome é um número de telefone
MIN_DIGITOS = 8                # quantos dígitos no nome para considerar "número de telefone"
MODO_TESTE = True              # é perguntado ao iniciar (s/n); este valor é só o padrão
ORGANIZAR_JANELAS = True       # deixa os LDs abertos lado a lado (igual ao botão do Multiplayer)
FECHAR_OS_OK = True            # fecha as instâncias que não estão banidas
TIMEOUT_BOOT = 180             # segundos máximos esperando o Android iniciar
ESPERA_WPP_MAX = 60            # segundos máximos esperando o WhatsApp abrir
LEITURAS = 4                   # quantas vezes lê a tela depois que o WhatsApp abriu
INTERVALO_LEITURA = 5          # segundos entre cada leitura
PACOTE_WPP = "com.whatsapp.w4b"   # WhatsApp Business (use "com.whatsapp" para o normal)

# Textos que aparecem na tela de banimento (PT e EN).
# Pode escrever com maiúscula/minúscula, tanto faz.
TEXTOS_BANIDO = [
    "está banido",
    "esta banido",
    "foi banido",
    "banido de usar o whatsapp",
    "is banned",
    "banned from using whatsapp",
    "conta foi banida",
    "não pode usar o whatsapp",
    "nao pode usar o whatsapp",
    "can't use whatsapp",
    "can’t use whatsapp",
    "cannot use whatsapp",
    "Alguma atividade na sua conta violou nossos Termos de Serviço",
    "Some activity on your account violated our Terms of Service",
    "alguma atividade na sua conta pode não ter seguido os Termos de Serviço",
    "some activity on your account may not have followed the Terms of Service",
    "Pedir revisão",
    "Essa conta não pode usar o WhatsApp",
]
# ============================================================

# Evita erro de acentuação no console do Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Pasta onde o script (ou o .exe) está — o relatório é salvo aqui
if getattr(sys, "frozen", False):
    PASTA = os.path.dirname(sys.executable)
else:
    PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "relatorio_ld.txt")


PROGRESSO = {}   # índice -> (posição, total)


def rotulo(indice, nome=None):
    """Ex.: LD #61 (7/42) 5511999990000"""
    pos, total = PROGRESSO.get(indice, (0, 0))
    texto = f"LD #{indice}"
    if total:
        texto += f" ({pos}/{total})"
    if nome:
        texto += f" {nome}"
    return texto


_TRAVA_LOG = threading.Lock()


def log(msg):
    with _TRAVA_LOG:
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def ld(*args, timeout=60):
    """Executa um comando do ldconsole e devolve a saída como texto."""
    return _rodar([LDCONSOLE, *map(str, args)], timeout)


ADB_EXE = os.path.join(os.path.dirname(LDCONSOLE), "adb.exe")


def serial(indice):
    """Endereço ADB da instância: o LD usa a porta 5555 + 2 x índice."""
    return f"127.0.0.1:{5555 + 2 * int(indice)}"


def _rodar(cmd, timeout):
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.stdout.decode("utf-8", errors="ignore").strip()
    except subprocess.TimeoutExpired:
        return ""


CHAVE_ADB = "basicSettings.adbDebug"   # 1 = Abrir conexão local / 0 = Fechado


def _config(indice):
    return os.path.join(os.path.dirname(LDCONSOLE), "vms", "config", f"leidian{indice}.config")


def _ler_cfg(indice):
    with open(_config(indice), "r", encoding="utf-8") as f:
        return json.load(f)


def _gravar_cfg(indice, dados):
    with open(_config(indice), "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)


def adb_ligado(indice):
    try:
        return _ler_cfg(indice).get(CHAVE_ADB, 0) == 1
    except Exception:
        return False


def _definir_adb(indice, valor):
    dados = _ler_cfg(indice)
    if dados.get(CHAVE_ADB, 0) == valor:
        return False
    dados[CHAVE_ADB] = valor
    _gravar_cfg(indice, dados)
    return True


def ligar_adb(indice, nome):
    """Liga a Depuração ADB (a instância precisa estar fechada)."""
    try:
        if _definir_adb(indice, 1):
            log(f"  ADB ligado em {rotulo(indice, nome)}")
        return True
    except Exception as e:
        log(f"  [AVISO] não consegui ligar o ADB em {rotulo(indice, nome)}: {e}")
        return False


def desligar_adb(indice, nome):
    """Desliga a Depuração ADB (a instância precisa estar fechada)."""
    _rodar([ADB_EXE, "disconnect", serial(indice)], timeout=15)
    if esta_rodando(indice):
        log(f"  [AVISO] {rotulo(indice, nome)} não fechou, ADB continua ligado")
        return
    try:
        if _definir_adb(indice, 0):
            log(f"  ADB desligado em {rotulo(indice, nome)}")
    except Exception as e:
        log(f"  [AVISO] não consegui desligar o ADB em {rotulo(indice, nome)}: {e}")


def preparar_e_abrir(indice, nome):
    """
    Garante que a instância vai abrir com ADB ligado:
      - fechada            -> liga o ADB e abre
      - aberta c/ ADB      -> deixa como está
      - aberta sem ADB     -> fecha, liga o ADB e abre de novo
    """
    if esta_rodando(indice):
        if adb_ligado(indice):
            log(f"{rotulo(indice, nome)} já estava aberto com ADB ligado")
            return
        log(f"{rotulo(indice, nome)} estava aberto sem ADB, reiniciando...")
        fechar(indice)
        time.sleep(2)
    ligar_adb(indice, nome)
    log(f"Abrindo {rotulo(indice, nome)}")
    ld("launch", "--index", indice)


def fechar_e_desligar(indice, nome):
    """Fecha o LD e SEMPRE desliga o ADB depois."""
    fechar(indice)
    time.sleep(2)
    desligar_adb(indice, nome)


def conectar(indice):
    """Conecta o ADB na instância (necessário para índices altos)."""
    _rodar([ADB_EXE, "connect", serial(indice)], timeout=15)


def adb(indice, comando, timeout=60):
    return _rodar([ADB_EXE, "-s", serial(indice), *comando.split()], timeout)


def listar_instancias():
    """Retorna lista de (indice, nome) usando 'ldconsole list2'."""
    saida = ld("list2")
    instancias = []
    for linha in saida.splitlines():
        partes = linha.split(",")
        if len(partes) >= 2 and partes[0].isdigit():
            instancias.append((int(partes[0]), partes[1]))
    return instancias


def nome_e_numero(nome):
    """True se o nome tem dígitos suficientes para ser um número de telefone."""
    return sum(c.isdigit() for c in nome) >= MIN_DIGITOS


def esta_rodando(indice):
    return "running" in ld("isrunning", "--index", indice).lower()


def esperar_boot(indice, nome):
    inicio = time.time()
    ultimo_aviso = 0
    while time.time() - inicio < TIMEOUT_BOOT:
        conectar(indice)
        if adb(indice, "shell getprop sys.boot_completed", timeout=15).strip().endswith("1"):
            log(f"  {rotulo(indice, nome)} iniciou em {int(time.time() - inicio)}s")
            time.sleep(5)  # margem para a launcher terminar de carregar
            organizar_janelas()  # a janela pode ter mudado de tamanho ao terminar de ligar
            ler_tela(indice)  # fecha aviso de "não está respondendo", se tiver
            return True
        passou = int(time.time() - inicio)
        if passou - ultimo_aviso >= 20:
            log(f"  aguardando boot de {rotulo(indice, nome)}... {passou}s")
            ultimo_aviso = passou
        time.sleep(4)
    log(f"  {rotulo(indice, nome)} não respondeu ao ADB. A Depuração ADB está ligada?")
    return False


# Aviso do Android "X não está respondendo" -> toca em "Aguardar"
TEXTOS_TRAVOU = [
    "não está respondendo", "nao esta respondendo", "não responde",
    "parou de responder", "isn't responding", "is not responding", "not responding",
]
BOTOES_AGUARDAR = ["aguardar", "esperar", "wait"]


def _dump_xml(indice, tentativas=3):
    """Faz dump da interface com uiautomator e devolve o XML cru."""
    for _ in range(tentativas):
        adb(indice, "shell uiautomator dump /sdcard/ui.xml", timeout=30)
        xml = adb(indice, "shell cat /sdcard/ui.xml", timeout=30)
        if "<hierarchy" in xml:
            return xml
        time.sleep(3)
    return ""


def _normalizar(texto):
    """Minúsculas, apóstrofo padrão e espaços/quebras de linha unificados."""
    texto = texto.lower().replace("’", "'")
    return re.sub(r"\s+", " ", texto).strip()


def _textos(xml):
    textos = re.findall(r'(?:text|content-desc)="([^"]*)"', xml)
    return _normalizar(html.unescape(" ".join(textos)))


def _tocar_aguardar(indice, xml):
    """Se for o aviso de 'não está respondendo', toca em Aguardar. Retorna True se tocou."""
    if not any(_normalizar(t) in _textos(xml) for t in TEXTOS_TRAVOU):
        return False
    for no in re.findall(r"<node [^>]*>", xml):
        m_txt = re.search(r' text="([^"]*)"', no)
        m_pos = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', no)
        if not m_txt or not m_pos:
            continue
        if html.unescape(m_txt.group(1)).strip().lower() in BOTOES_AGUARDAR:
            x1, y1, x2, y2 = map(int, m_pos.groups())
            adb(indice, f"shell input tap {(x1 + x2) // 2} {(y1 + y2) // 2}", timeout=15)
            log(f"  {rotulo(indice)}: aviso de 'não está respondendo' -> toquei em Aguardar")
            return True
    return False


def foco_atual(indice):
    """Linha 'mCurrentFocus' do Android: diz qual janela está na frente."""
    saida = adb(indice, "shell dumpsys window", timeout=30)
    for linha in saida.splitlines():
        if "mCurrentFocus" in linha:
            return linha.strip()
    return ""


def _popup_travou(foco):
    """Aviso de travamento/erro do Android (funciona mesmo com o app congelado)."""
    f = foco.lower()
    return "not responding" in f or "application error" in f


def limpar_popups(indice):
    """
    Confere se tem aviso de 'não está respondendo' na frente e resolve:
      1) tenta ler a tela e tocar em Aguardar
      2) se não conseguir ler (app congelado), fecha o app travado e,
         se for o WhatsApp, abre ele de novo
    Retorna True se encontrou e tratou algum aviso.
    """
    tratou = False
    for _ in range(4):
        foco = foco_atual(indice)
        if not _popup_travou(foco):
            return tratou
        tratou = True
        xml = _dump_xml(indice, tentativas=1)
        if xml and _tocar_aguardar(indice, xml):
            time.sleep(3)
            continue
        m = re.search(r":\s*([\w.]+)\}?\s*$", foco)
        pacote = m.group(1) if m else ""
        if pacote and pacote != "com.android.systemui":
            log(f"  {rotulo(indice)}: '{pacote}' travado e não deu para tocar em Aguardar -> fechando e reabrindo")
            adb(indice, f"shell am force-stop {pacote}", timeout=15)
            time.sleep(2)
            if pacote == PACOTE_WPP:
                ld("runapp", "--index", indice, "--packagename", PACOTE_WPP)
                time.sleep(3)
        else:
            log(f"  {rotulo(indice)}: aviso do sistema sem botão legível -> apertando voltar")
            adb(indice, "shell input keyevent 4", timeout=15)
            time.sleep(2)
    return tratou


def ler_tela(indice):
    """
    Lê os textos da tela (em minúsculas). Antes, sempre confere se tem
    aviso de 'não está respondendo' na frente e resolve.
    """
    limpar_popups(indice)
    for _ in range(4):
        xml = _dump_xml(indice)
        if not xml:
            return ""
        if _tocar_aguardar(indice, xml):
            time.sleep(3)
            continue
        return _textos(xml)
    return _textos(xml)


def wpp_instalado(indice):
    saida = adb(indice, f"shell pm list packages {PACOTE_WPP}", timeout=30)
    return f"package:{PACOTE_WPP}" in [l.strip() for l in saida.splitlines()]


def wpp_em_primeiro_plano(indice):
    """True se a janela em foco é do WhatsApp (tela normal OU caixa de diálogo dele)."""
    limpar_popups(indice)
    foco = foco_atual(indice)
    if _popup_travou(foco):
        return False
    return re.search(re.escape(PACOTE_WPP) + r"[/}\s]", foco + " ") is not None


def tela_banida(indice):
    """Lê a tela. Retorna (texto_lido, banido?)."""
    tela = ler_tela(indice)
    return tela, bool(tela) and any(_normalizar(t) in tela for t in TEXTOS_BANIDO if t.strip())


def _voltar_e_reabrir(indice):
    adb(indice, "shell input keyevent 4", timeout=15)   # botão voltar
    time.sleep(1)
    ld("runapp", "--index", indice, "--packagename", PACOTE_WPP)


def _ultima_chance(indice):
    """
    Antes de dar erro: limpa avisos de travamento, espera o WhatsApp voltar
    pra frente (até 20s) e lê a tela de novo.
    Retorna "banido", "ok" ou None (continua sem conseguir).
    """
    log(f"  {rotulo(indice)}: última tentativa antes de marcar erro...")
    limpar_popups(indice)
    inicio = time.time()
    while time.time() - inicio < 20:
        tela, banido = tela_banida(indice)
        if banido:
            return "banido"
        if tela and wpp_em_primeiro_plano(indice):
            return "ok"
        if not wpp_em_primeiro_plano(indice):
            ld("runapp", "--index", indice, "--packagename", PACOTE_WPP)
        time.sleep(4)
    return None


def checar_banido(indice):
    """
    Retorna:
      "banido"     -> tela de banimento encontrada
      "ok"         -> WhatsApp abriu e não tem tela de ban
      "sem_wpp"    -> WhatsApp não está instalado
      "nao_abriu"  -> WhatsApp não abriu dentro do tempo
      "erro_tela"  -> não conseguiu ler a tela

    Regra principal: o texto de ban na tela SEMPRE vale, mesmo que o Android
    não diga que o WhatsApp está em foco. Ele só aperta "voltar" depois de
    ler a tela e confirmar que não é um aviso de ban.
    """
    if not wpp_instalado(indice):
        return "sem_wpp"

    limpar_popups(indice)
    ld("runapp", "--index", indice, "--packagename", PACOTE_WPP)

    # Espera o WhatsApp ficar em primeiro plano
    inicio = time.time()
    tentativas = 0
    while not wpp_em_primeiro_plano(indice):
        if time.time() - inicio > ESPERA_WPP_MAX:
            return _ultima_chance(indice) or "nao_abriu"
        time.sleep(3)
        tentativas += 1
        if tentativas % 4 == 0:   # a cada ~12s: confere ban ANTES de tentar fechar anúncio
            _, banido = tela_banida(indice)
            if banido:
                return "banido"
            _voltar_e_reabrir(indice)

    # Lê a tela algumas vezes (a tela de ban pode demorar a aparecer
    # depois do splash "from Meta")
    leituras_ok = 0
    for _ in range(LEITURAS + 3):          # tentativas extras por causa de anúncios
        time.sleep(INTERVALO_LEITURA)
        tela, banido = tela_banida(indice)
        if banido:
            return "banido"
        if not wpp_em_primeiro_plano(indice):
            _voltar_e_reabrir(indice)      # é anúncio/pop-up, não ban
            continue
        if tela:
            leituras_ok += 1
            if leituras_ok >= LEITURAS:
                break

    if leituras_ok == 0:
        resultado = _ultima_chance(indice)
        if resultado:
            return resultado
        return "nao_abriu" if not wpp_em_primeiro_plano(indice) else "erro_tela"
    return "ok"


def fechar(indice):
    ld("quit", "--index", indice)
    for _ in range(30):
        if not esta_rodando(indice):
            return True
        time.sleep(2)
    return False


def excluir(indice, nome):
    """Exclui a instância. Retorna True se excluiu de verdade."""
    fechar(indice)
    if MODO_TESTE:
        log(f"  [MODO TESTE] excluiria {rotulo(indice, nome)}")
        return False
    time.sleep(3)
    ld("remove", "--index", indice, timeout=120)
    log(f"  [EXCLUIDO] {rotulo(indice, nome)}")
    return True


def organizar_janelas():
    if ORGANIZAR_JANELAS:
        ld("sortWnd")


def processar_um(indice, nome, res):
    """Um 'trabalhador': abre, confere e fecha um LD. Rodam LOTE desses em paralelo."""
    try:
        preparar_e_abrir(indice, nome)
        time.sleep(5)          # espera a janela aparecer
        organizar_janelas()
        verificar(indice, nome, res)
    except Exception as e:
        log(f"  [ERRO] {rotulo(indice, nome)} erro inesperado: {e}")
        res["erro"].append((indice, nome, f"erro inesperado: {e}"))
        try:
            fechar_e_desligar(indice, nome)
        except Exception:
            pass


def verificar(indice, nome, res):
    if not esperar_boot(indice, nome):
        log(f"  [ERRO] {rotulo(indice, nome)} não iniciou a tempo")
        res["erro"].append((indice, nome, "LD não iniciou a tempo / ADB não respondeu"))
        fechar_e_desligar(indice, nome)
        return

    status = checar_banido(indice)
    if status == "banido":
        log(f"  [BANIDO] {rotulo(indice, nome)}")
        res["banidas"].append((indice, nome, ""))
        if excluir(indice, nome):
            res["limpas"].append(nome)
            return                      # instância apagada, nada a desligar
        fechar_e_desligar(indice, nome)  # modo teste: continua existindo
        return

    if status == "ok":
        log(f"  [OK] {rotulo(indice, nome)}")
        res["ok"].append(nome)
        if not FECHAR_OS_OK:
            return                      # fica aberto, então o ADB fica ligado
    elif status == "sem_wpp":
        log(f"  [SEM WPP] {rotulo(indice, nome)} não tem WhatsApp instalado")
        res["sem_wpp"].append((indice, nome, ""))
    elif status == "nao_abriu":
        log(f"  [ERRO] {rotulo(indice, nome)} WhatsApp não abriu")
        res["nao_abriu"].append((indice, nome, ""))
    else:
        log(f"  [ERRO] {rotulo(indice, nome)} não consegui ler a tela")
        res["erro"].append((indice, nome, "não conseguiu ler a tela"))
    fechar_e_desligar(indice, nome)


def _nomes(lista):
    return ", ".join(f"#{i} {n}" for i, n, _ in lista)


def relatorio(total_pc, verificadas, res, ignoradas):
    linhas = [
        "=" * 42,
        f"RELATÓRIO - {datetime.datetime.now():%d/%m/%Y %H:%M}",
        "=" * 42,
        f"Emuladores no PC ......: {total_pc}",
        f"Verificados ...........: {verificadas}",
        f"OK ....................: {len(res['ok'])}",
        f"Banidos ...............: {len(res['banidas'])}",
        f"Limpos (excluídos) ....: {len(res['limpas'])}",
        f"Sem WhatsApp ..........: {len(res['sem_wpp'])}",
        f"WhatsApp não abriu ....: {len(res['nao_abriu'])}",
        f"Outros erros ..........: {len(res['erro'])}",
    ]
    if res["banidas"]:
        linhas.append("Banidos: " + _nomes(res["banidas"]))
    if res["sem_wpp"]:
        linhas.append("Sem WhatsApp: " + _nomes(res["sem_wpp"]))
    if res["nao_abriu"]:
        linhas.append("WhatsApp não abriu: " + _nomes(res["nao_abriu"]))
    if res["erro"]:
        linhas.append("Outros erros: " + _nomes(res["erro"]))
    if ignoradas:
        linhas.append("Ignorados (nome não é número): " + ", ".join(ignoradas))
    if MODO_TESTE:
        linhas.append("(MODO TESTE - nada foi excluído)")

    texto = "\n".join(linhas)
    print("\n" + texto)
    with open(RELATORIO, "a", encoding="utf-8") as f:
        f.write(texto + "\n\n")
    print(f"\nRelatório salvo em: {RELATORIO}")


def lista_pendentes(res):
    """Gera um .txt com os LDs para conferir manualmente e abre no Bloco de Notas."""
    grupos = [
        ("1. SEM WHATSAPP", res["sem_wpp"]),
        ("2. NÃO CONSEGUIU ABRIR O WHATSAPP", res["nao_abriu"]),
        ("3. OUTROS ERROS", res["erro"]),
    ]
    if MODO_TESTE:
        grupos.append(("4. BANIDOS (modo teste: NÃO foram excluídos - confira e exclua)", res["banidas"]))
    if not any(lista for _, lista in grupos):
        log("Nenhum LD para conferir manualmente.")
        return

    agora = datetime.datetime.now()
    linhas = [f"LDs PARA CONFERIR MANUALMENTE - {agora:%d/%m/%Y %H:%M}", ""]
    for titulo, lista in grupos:
        linhas.append(f"{titulo} ({len(lista)})")
        linhas.append("-" * 42)
        if not lista:
            linhas.append("   (nenhum)")
        for indice, nome, motivo in lista:
            linha = f"   #{indice:<5} {nome}"
            if motivo:
                linha += f"   -> {motivo}"
            linhas.append(linha)
        linhas.append("")

    caminho = os.path.join(PASTA, f"conferir_{agora:%Y%m%d_%H%M}.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    log(f"Lista para conferir salva em: {caminho}")
    if os.name == "nt":
        subprocess.Popen(["notepad.exe", caminho])


def perguntar_modo_teste():
    """Pergunta se é modo teste. Enter sozinho = sim (mais seguro)."""
    while True:
        r = input("Iniciar em modo teste? (s/n) [s]: ").strip().lower()
        if r in ("", "s", "sim"):
            return True
        if r in ("n", "nao", "não"):
            confirma = input("ATENÇÃO: os banidos serão EXCLUÍDOS. Confirmar? (s/n): ").strip().lower()
            if confirma in ("s", "sim"):
                return False
            continue
        print("Responda s ou n.")


def main():
    global MODO_TESTE
    MODO_TESTE = perguntar_modo_teste()
    print()

    if not os.path.exists(LDCONSOLE):
        log(f"[ERRO] ldconsole.exe não encontrado em: {LDCONSOLE}")
        log("Ajuste a variável LDCONSOLE no topo do script.")
        return

    if not os.path.exists(ADB_EXE):
        log(f"[ERRO] adb.exe não encontrado em: {ADB_EXE}")
        return
    _rodar([ADB_EXE, "start-server"], timeout=30)

    if MODO_TESTE:
        log("MODO TESTE ligado: nada será excluído.")

    todas = listar_instancias()
    instancias, ignoradas = [], []
    for indice, nome in todas:
        if indice in PULAR_INDICES:
            continue
        if SO_NOMES_COM_NUMERO and not nome_e_numero(nome):
            ignoradas.append(nome)
            continue
        instancias.append((indice, nome))

    log(f"Emuladores no PC: {len(todas)} | Para verificar: {len(instancias)}")
    if ignoradas:
        log(f"Ignorados (nome não é número): {', '.join(ignoradas)}")

    res = {"ok": [], "banidas": [], "limpas": [], "sem_wpp": [], "nao_abriu": [], "erro": []}
    for pos, (indice, _) in enumerate(instancias, 1):
        PROGRESSO[indice] = (pos, len(instancias))

    # LOTE trabalhadores em paralelo: quando um termina, já pega o próximo da fila
    with ThreadPoolExecutor(max_workers=LOTE) as pool:
        for indice, nome in instancias:
            pool.submit(processar_um, indice, nome, res)

    relatorio(len(todas), len(instancias), res, ignoradas)
    lista_pendentes(res)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    input("\nPressione Enter para sair...")