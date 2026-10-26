"""
Ativar ADB em todos os LDs
Copia a configuração de "Depuração ADB" de uma instância modelo (onde você já
ativou manualmente) para todas as instâncias com número no nome.

Antes de rodar:
  1. Ative a Depuração ADB -> "Abrir conexão local" na instância MODELO.
  2. FECHE todos os LDs (senão o LD sobrescreve a configuração ao fechar).
Uso: python ativar_adb.py
"""

import datetime
import json
import os
import shutil
import subprocess
import sys

# ======================= CONFIGURAÇÕES =======================
PASTA_LD = r"C:\LDPlayer\LDPlayer9"
MODELO = 21            # índice da instância onde você ativou o ADB manualmente
MIN_DIGITOS = 8        # só altera instâncias cujo nome tem esse tanto de dígitos
# ============================================================

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LDCONSOLE = os.path.join(PASTA_LD, "ldconsole.exe")
PASTA_CONFIG = os.path.join(PASTA_LD, "vms", "config")


def listar():
    r = subprocess.run([LDCONSOLE, "list2"], capture_output=True)
    saida = r.stdout.decode("utf-8", errors="ignore")
    inst = []
    for linha in saida.splitlines():
        p = linha.split(",")
        if len(p) >= 5 and p[0].isdigit():
            inst.append({"indice": int(p[0]), "nome": p[1], "rodando": p[4] == "1"})
    return inst


def caminho_config(indice):
    return os.path.join(PASTA_CONFIG, f"leidian{indice}.config")


def ler_json(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    if not os.path.exists(LDCONSOLE):
        print(f"[ERRO] Não achei o LDPlayer em {PASTA_LD}")
        return

    instancias = listar()
    rodando = [i for i in instancias if i["rodando"]]
    if rodando:
        print("[ERRO] Feche todos os LDs antes de rodar. Ainda abertos:")
        for i in rodando:
            print(f"   #{i['indice']} ({i['nome']})")
        return

    modelo_cfg = caminho_config(MODELO)
    if not os.path.exists(modelo_cfg):
        print(f"[ERRO] Não achei o arquivo da instância modelo: {modelo_cfg}")
        return

    modelo = ler_json(modelo_cfg)
    chaves_adb = {k: v for k, v in modelo.items() if "adb" in k.lower()}
    if not chaves_adb:
        print(f"[ERRO] A instância #{MODELO} não tem configuração de ADB salva.")
        print("Ative a Depuração ADB nela, salve, feche o LD e rode de novo.")
        return

    print(f"Configuração de ADB encontrada no #{MODELO}:")
    for k, v in chaves_adb.items():
        print(f"   {k} = {v}")
    print()

    alvos = [
        i for i in instancias
        if i["indice"] != MODELO and sum(c.isdigit() for c in i["nome"]) >= MIN_DIGITOS
    ]
    print(f"Vou aplicar em {len(alvos)} instâncias.")
    if input("Continuar? (s/n) ").strip().lower() != "s":
        print("Cancelado.")
        return

    pasta_backup = os.path.join(
        PASTA_LD, "vms", f"config_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    )
    os.makedirs(pasta_backup, exist_ok=True)

    ok, falhas = 0, []
    for i in alvos:
        cfg = caminho_config(i["indice"])
        try:
            if not os.path.exists(cfg):
                raise FileNotFoundError("arquivo de config não existe")
            shutil.copy2(cfg, pasta_backup)
            dados = ler_json(cfg)
            dados.update(chaves_adb)
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)
            print(f"   [OK] #{i['indice']} ({i['nome']})")
            ok += 1
        except Exception as e:
            print(f"   [ERRO] #{i['indice']} ({i['nome']}): {e}")
            falhas.append(i["nome"])

    print()
    print(f"ADB ativado em {ok} instâncias.")
    if falhas:
        print("Falharam: " + ", ".join(falhas))
    print(f"Backup dos arquivos originais em: {pasta_backup}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
    input("\nPressione Enter para sair...")