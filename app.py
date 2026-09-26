"""ATRIA · Plataforma de recomendação — interface Streamlit.

Rodar localmente:  streamlit run app.py
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ASSETS = Path(__file__).parent / "assets"
VERDE, LARANJA, VERMELHO_SUB = "#104A2A", "#E25A10", "#FF8A8A"
APP_VERSAO = "10.0"          # tem de ser igual a motor/__init__.py → VERSAO

st.set_page_config(page_title="ATRIA · Recomendação de solo", page_icon=str(ASSETS / "selo.png"),
                   layout="wide")

try:
    from motor import VERSAO
except ImportError:
    VERSAO = "antiga"
try:
    from motor import (Ajustes, AjusteProduto, Parametros, gerar_excel, gerar_excel_interpretacao,
                       ler_laudo, recomendar)
    from motor import interpretacao as it
    from motor.processar import (COL_CAL, COL_GES, COL_K, COL_K1, COL_P, COL_S0, COL_SUB,
                                 colunas_doses, colunas_doses_totais, nome_produto_p)
    from motor.juntar import identificacao, juntar as juntar_laudos, sugerir_grupos
    from motor.regras import fatores_calcario, ler_formula
    erro_import = None
except Exception as e:  # noqa: BLE001
    erro_import = e
if erro_import is not None or VERSAO != APP_VERSAO:
    st.error(f"**Os arquivos do app estão em versões diferentes** (app.py = {APP_VERSAO}, pasta `motor` = {VERSAO}).\n\n"
             "No GitHub, a pasta **`motor`** precisa ser atualizada junto com o `app.py`: abra a pasta `motor` do "
             "repositório, clique em *Add file → Upload files* e arraste para lá **todos os arquivos da pasta "
             "`motor`** do .zip (os `.py`). Depois, em *Manage app → ⋮ → Reboot app*.")
    if erro_import is not None:
        st.caption(f"Detalhe técnico: {type(erro_import).__name__}: {erro_import}")
    st.stop()

st.markdown(f"""
<style>
  h1, h2, h3 {{ color: {VERDE}; }}
  .atria-titulo {{ font-size: 1.9rem; font-weight: 800; color: {VERDE}; margin: .6rem 0 0 0; }}
  .atria-sub {{ color: #5b6b61; margin-bottom: .4rem; }}
  .atria-faixa {{ height: 5px; background: {LARANJA}; border-radius: 3px; margin: .2rem 0 1rem 0; }}
  [data-testid="stMetricValue"] {{ color: {VERDE}; }}
  .sub-legenda {{ display:inline-block; width:14px; height:14px; background:{VERMELHO_SUB};
                  border-radius:3px; vertical-align:middle; margin-right:6px; }}
</style>""", unsafe_allow_html=True)


def br(x, casas: int = 0) -> str:
    """Número com separador de milhar brasileiro."""
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def segredo(chave: str):
    try:
        return st.secrets.get(chave)
    except Exception:
        return None


# ------------------------------------------------------------ senha opcional
def liberado() -> bool:
    senha = segredo("senha")
    if not senha or st.session_state.get("ok"):
        return True
    st.image(str(ASSETS / "logo.png"), width=260)
    s = st.text_input("Senha de acesso", type="password")
    if s:
        if s == senha:
            st.session_state.ok = True
            st.rerun()
        st.error("Senha incorreta")
    return False


if not liberado():
    st.stop()

st.logo(str(ASSETS / "logo.png"), icon_image=str(ASSETS / "selo.png"), size="large")


# ------------------------------------------------------------------- música
PLAYLIST_PADRAO = "https://www.youtube.com/watch?v=JcrBHxWHX74&list=RDJcrBHxWHX74&start_radio=1"


def url_embed(link: str) -> str | None:
    """Converte link do YouTube (vídeo, playlist ou Mix) ou do Spotify em link de player incorporado."""
    link = (link or "").strip()
    video = re.search(r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/)([\w-]{11})", link)
    lista = re.search(r"[?&]list=([\w-]+)", link)
    if video and lista:      # vídeo dentro de uma lista ou Mix (RD...): começa pelo vídeo e segue a lista
        return (f"https://www.youtube.com/embed/{video.group(1)}?list={lista.group(1)}"
                f"&autoplay=1&loop=1&rel=0")
    if lista:                # playlist comum
        return f"https://www.youtube.com/embed/videoseries?list={lista.group(1)}&autoplay=1&loop=1"
    if video:
        return f"https://www.youtube.com/embed/{video.group(1)}?autoplay=1&loop=1&playlist={video.group(1)}"
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(playlist|album|track)/(\w+)", link)
    if m:
        return f"https://open.spotify.com/embed/{m.group(1)}/{m.group(2)}"
    return None


with st.sidebar:
    musica = st.toggle("🎵 Trilha sonora", value=False, help="Liga/desliga a música de fundo")
    if musica:
        link = st.session_state.get("playlist_link") or segredo("playlist") or PLAYLIST_PADRAO
        emb = url_embed(link)
        if emb:
            altura = 152 if "spotify" in emb else 180
            components.html(
                f'<iframe src="{emb}" width="100%" height="{altura}" frameborder="0" '
                f'style="border-radius:10px" allow="autoplay; encrypted-media; clipboard-write" '
                f'allowfullscreen></iframe>', height=altura + 8)
        with st.expander("Trocar playlist", expanded=not emb):
            st.text_input("Link da playlist (YouTube ou Spotify)", key="playlist_link",
                          placeholder="https://www.youtube.com/playlist?list=...")
            st.caption("Para fixar para todos, coloque `playlist = \"link\"` nos Secrets do app.")
    st.divider()

PADRAO = Parametros()

# ----------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("Calcário utilizado")
    st.caption(f"Modelo calibrado para CaO {PADRAO.calcario.ref_cao:g}% · MgO "
               f"{PADRAO.calcario.ref_mgo:g}% · PRNT {PADRAO.calcario.ref_prnt:g}")
    cao = st.number_input("CaO (%)", 0.0, 60.0, PADRAO.calcario.cao, 0.1)
    mgo = st.number_input("MgO (%)", 0.0, 30.0, PADRAO.calcario.mgo, 0.1)
    prnt = st.number_input("PRNT (%)", 30.0, 150.0, PADRAO.calcario.prnt, 1.0)

    with st.expander("Regras (avançado)"):
        st.markdown("**Calcário**")
        c_min = st.number_input("Dose mínima (kg/ha)", 0.0, 5000.0, PADRAO.calcario.dose_min, 50.0)
        c_max = st.number_input("Dose máxima (kg/ha)", 0.0, 10000.0, PADRAO.calcario.dose_max, 100.0)
        fab = st.number_input("Fator de abertura", 1.0, 3.0, PADRAO.calcario.fator_abertura, 0.1)
        ordem = st.radio("Na abertura, o fator é aplicado…",
                         ["depois dos limites (720–6840 kg/ha)", "antes dos limites (máx. = dose máxima)"])
        k_med = st.checkbox("Usar K do laudo na CTC* (em vez da constante 5,6)", PADRAO.calcario.usar_k_medido)
        st.markdown("**Gesso**")
        g_min = st.number_input("Gesso mínimo (kg/ha)", 0.0, 2000.0, PADRAO.gesso.dose_min, 50.0)
        g_max = st.number_input("Gesso máximo (kg/ha)", 0.0, 5000.0, PADRAO.gesso.dose_max, 100.0)
        s1 = st.number_input("S alvo, argila < 200 g/kg", 0.0, 100.0, PADRAO.gesso.s_alvo_arenoso, 1.0)
        s2 = st.number_input("S alvo, argila 200–400 g/kg", 0.0, 100.0, PADRAO.gesso.s_alvo_medio, 1.0)
        s3 = st.number_input("S alvo, argila > 400 g/kg", 0.0, 100.0, PADRAO.gesso.s_alvo_argiloso, 1.0)
        st.markdown("**P2O5 e KCl**")
        p_min = st.number_input("P2O5 mínimo (kg/ha)", 0.0, 300.0, PADRAO.fosforo.dose_min, 5.0)
        p_max = st.number_input("P2O5 máximo (kg/ha)", 0.0, 300.0, PADRAO.fosforo.dose_max, 5.0)
        k_min = st.number_input("KCl mínimo (kg/ha)", 0.0, 500.0, PADRAO.potassio.dose_min, 10.0)

par = Parametros(
    calcario=replace(PADRAO.calcario, cao=cao, mgo=mgo, prnt=prnt, dose_min=c_min, dose_max=c_max,
                     fator_abertura=fab, abertura_antes_dos_limites=ordem.startswith("antes"),
                     usar_k_medido=k_med),
    gesso=replace(PADRAO.gesso, dose_min=g_min, dose_max=g_max,
                  s_alvo_arenoso=s1, s_alvo_medio=s2, s_alvo_argiloso=s3),
    fosforo=replace(PADRAO.fosforo, dose_min=p_min, dose_max=p_max),
    potassio=replace(PADRAO.potassio, dose_min=k_min),
)
f = fatores_calcario(par.calcario)
if any(abs(f[k] - 1) > 1e-9 for k in ("ca", "mg", "prnt")):
    st.sidebar.info(f"Correção da dose de calcário: critério Ca ×{f['ca'] * f['prnt']:.2f} · "
                    f"critério Mg ×{f['mg'] * f['prnt']:.2f}")

# ------------------------------------------------------------------ topo
st.image(str(ASSETS / "banner.jpg"), width="stretch")
st.markdown('<div class="atria-titulo">Recomendação de calcário, gesso, P2O5 e KCl</div>'
            '<div class="atria-sub">Anexe o laudo de análise de solo (Excel). O sistema lê as colunas, '
            'aplica as regras e gera a planilha de recomendações e a interpretação por talhão.</div>'
            '<div class="atria-faixa"></div>', unsafe_allow_html=True)

@st.cache_data(show_spinner=False, max_entries=40)
def ler_laudo_cache(conteudo: bytes, nome: str, versao: str = VERSAO):
    return ler_laudo(conteudo, nome)



def bloco_ajuste(col, titulo: str, media_regra: float, chave: str, rotulo_produto: str,
                 antes=None) -> AjusteProduto:
    """Controles de ajuste de um produto; devolve o AjusteProduto escolhido."""
    with col:
        st.markdown(f"**{titulo}**")
        if antes:
            antes()
        st.caption(f"Média pela regra: **{br(media_regra)} kg/ha**")
        comprou = st.checkbox("Cliente já comprou", key=f"{chave}_comprou",
                              help=f"Se o cliente já comprou {rotulo_produto}, informe a média (kg/ha) "
                                   "que o volume comprado permite. A coluna inteira é ajustada, "
                                   "mantendo as proporções entre as amostras.")
        if comprou:
            alvo = st.number_input("Média a atingir (kg/ha)", min_value=0.0,
                                   value=float(round(media_regra or 0)), step=10.0, format="%.0f",
                                   key=f"{chave}_alvo")
            return AjusteProduto(media_alvo=alvo)
        pct = st.number_input("Ajuste (%)", -90.0, 300.0, 0.0, 5.0, format="%.0f", key=f"{chave}_pct",
                              help="Ex.: 10 = aumenta todas as doses em 10%; −15 = reduz 15%.")
        return AjusteProduto(pct=pct)


def sem_attrs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.attrs = {}
    return df


@st.cache_data(show_spinner=False, max_entries=80)
def png_interpretacao(tipo: str, df: pd.DataFrame, *extra) -> bytes:
    """Figuras da aba de interpretação, guardadas em cache (não são refeitas a cada clique)."""
    from types import SimpleNamespace
    df = df.copy()
    df.attrs = {}
    with it.TRAVA_MPL:
        if tipo == "mapa":
            fig = it.figura_mapa(df)
        elif tipo == "panorama":
            fig = it.figura_panorama(df)
        elif tipo == "classes":
            fig = it.figura_classes_amostras(SimpleNamespace(dados=df))
        elif tipo == "bases":
            fig = it.figura_bases(df, *extra)
        else:
            fig = it.figura_doses(df, list(extra[0]))
        return it.figura_png(fig)


def adiado(funcao, *args):
    """Função sem argumentos para o download_button: o arquivo só é montado quando o usuário clica."""
    def gerar():
        with it.TRAVA_MPL:
            return funcao(*args)
    return gerar


def estilo_linhas(df: pd.DataFrame, sub: pd.Series):
    def cor(row):
        return [f"background-color: {VERMELHO_SUB}" if sub.loc[row.name] else "" for _ in row]
    doses = colunas_doses(df)
    df = df.copy()
    df.attrs = {}
    df["N Lab"] = df["N Lab"].astype(str)
    for c in doses:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (df.style.apply(cor, axis=1)
            .format({c: (lambda v: "" if pd.isna(v) else br(v)) for c in doses}))


def avisos_distancia(proj, laudo) -> list[str]:
    """Laudos juntados: avisa quando os talhões de um arquivo estão longe dos demais."""
    if not getattr(laudo, "origens", None) or "_arquivo" not in laudo.dados:
        return []
    from motor.geo import chave_talhao
    from shapely.ops import unary_union
    arq_de = {chave_talhao(t): a for t, a in zip(laudo.dados["talhao"], laudo.dados["_arquivo"])}
    por_arq: dict[str, list] = {}
    for t in proj.talhoes:
        por_arq.setdefault(arq_de.get(t.chave, "?"), []).append(t.perimetro)
    if len(por_arq) < 2:
        return []
    geoms = {a: unary_union(g) for a, g in por_arq.items()}
    avisos = []
    for a, g in geoms.items():
        resto = unary_union([h for b, h in geoms.items() if b != a])
        d = g.distance(resto) / 1000
        if d > 5:
            avisos.append(f"Os talhões de **{a}** estão a {d:.1f} km dos demais. Confira se são mesmo da mesma "
                          "fazenda (se não forem, separe os laudos no quadro 🔗 lá em cima).")
    return avisos


def editor_blocos(proj, k0: str) -> dict[str, str]:
    """Blocos de aplicação: talhões com o mesmo nome de bloco saem numa prescrição/shapefile só."""
    with st.expander("🧩 Unir talhões na prescrição (opcional)"):
        st.caption("Para o produtor que prefere poucos arquivos: talhões com o **mesmo nome de bloco** "
                   "(ex.: *Bloco A*, *Pivô 1*) recebem as mesmas doses de zona e saem num **shapefile único por "
                   "produto**. Deixe em branco para manter o talhão separado. Os mapas de fertilidade e os "
                   "volumes por talhão não mudam.")
        todos = st.checkbox("Todos os talhões num bloco só", key=f"todos_bloco_{k0}")
        if todos:
            return {t.nome: "Fazenda" for t in proj.talhoes}
        tab = st.data_editor(
            pd.DataFrame({"Talhão": [t.nome for t in proj.talhoes],
                          "Área (ha)": [round(t.area_ha, 1) for t in proj.talhoes],
                          "Bloco": [""] * len(proj.talhoes)}),
            hide_index=True, disabled=["Talhão", "Área (ha)"], key=f"blocos_{k0}",
            column_config={"Bloco": st.column_config.TextColumn("Bloco de aplicação",
                                                                help="Mesmo nome = prescritos juntos")})
        blocos = {t: str(b).strip() for t, b in zip(tab["Talhão"], tab["Bloco"]) if b and str(b).strip()}
        contagem = pd.Series(list(blocos.values())).value_counts() if blocos else pd.Series(dtype=int)
        juntos = contagem[contagem > 1]
        if len(juntos):
            st.success(" · ".join(f"**{b}**: {n} talhões" for b, n in juntos.items()))
        return blocos


def bloco_shapefiles(r: dict, k0: str) -> None:
    """Escolha dos produtos para exportar em shapefile (P₂O₅ puro só com liberação explícita)."""
    from motor.prescricao import zip_prescricoes
    itens = r.get("blocos") or r["mapas"]
    produtos = list(dict.fromkeys(p for m in itens for p in m.zonas))
    tem_produto_p = any(p.startswith("Produto") for p in produtos)
    parcelado = any("aplicação" in p for p in produtos)
    st.markdown("##### Shapefiles de prescrição")
    liberar_p = False
    if not tem_produto_p:
        st.warning("Sem formulação fosfatada, a prescrição de fósforo está em **P₂O₅ (nutriente puro, "
                   "equivalente a um produto 00-100-00 que não existe)** — não serve para o controlador. "
                   "Informe a formulação comprada no formulário acima e gere de novo.")
        liberar_p = st.checkbox("Liberar mesmo assim o shapefile de P₂O₅ (só para conversão manual)",
                                key=f"libp_{k0}")
    opcoes = [p for p in produtos if p != "P2O5" or liberar_p]
    padrao = [p for p in opcoes if p != "P2O5" and not (parcelado and p == "KCl")]
    escolha = st.multiselect("Produtos para baixar", opcoes, default=padrao, key=f"prods_{k0}",
                             help="Uma pasta por talhão, um shapefile por produto (WGS84, campo Taxa_Dest_).")
    if escolha:
        mapas, epsg = itens, r["epsg"]
        st.download_button(f"🗂️ Baixar shapefiles ({len(escolha)} produto{'s' if len(escolha) > 1 else ''}, .zip)",
                           lambda: zip_prescricoes(mapas, epsg, produtos=escolha),
                           file_name=f"Prescricoes - {r['nome']}.zip", mime="application/zip",
                           help="Uma pasta por talhão ou bloco de aplicação, um shapefile por produto.",
                           width="stretch", key=f"dlz_{k0}")


def aba_montar_book(laudo, par, abertura, ajustes, k0, nome_laudo):
    """Mapas (krigagem), prescrições em shapefile e book em PDF."""
    from motor.book import MARCAS, DadosBook, montar_book
    from motor.externos import FONTES_SATELITE
    from motor.geo import ler_kml, montar_projeto, numero_talhao
    from motor.prescricao import calcular_doses, gerar_todas_zonas, superficies, tabela_volumes

    st.markdown("Anexe os **KML/KMZ de perímetro e de pontos** de cada talhão. Os pontos de cada talhão "
                "são ligados às amostras do laudo pela ordem (1, 2, 3…); amostras de 20-40 cm herdam o "
                "ponto da amostra de mesmo número.")
    kmls_up = st.file_uploader("Arquivos KML/KMZ", type=["kml", "kmz"], accept_multiple_files=True,
                               key=f"kml_{k0}")
    if not kmls_up:
        st.info("Nomeie os arquivos com o talhão (ex.: Perimetro_TH_1.kml, Pontos_TH_1.kml) — "
                "ou indique o talhão na tabela que aparece após o envio.")
        return
    kmls, erros = [], []
    for f in kmls_up:
        try:
            kmls.append(ler_kml(f.getvalue(), f.name))
        except Exception as e:  # noqa: BLE001
            erros.append(f"{f.name}: {e}")
    for e in erros:
        st.error(e)
    talhoes_laudo = list(dict.fromkeys(laudo.dados["talhao"]))
    tab = pd.DataFrame({"Arquivo": [k.nome for k in kmls],
                        "Tipo": [{"perimetro": "Perímetro", "pontos": "Pontos"}.get(k.tipo, k.tipo) for k in kmls],
                        "Pontos": [len(k.pontos) for k in kmls],
                        "Talhão": [numero_talhao(k.nome) or "" for k in kmls]})
    tab = st.data_editor(tab, hide_index=True, disabled=["Arquivo", "Tipo", "Pontos"], key=f"kmltab_{k0}",
                         column_config={"Talhão": st.column_config.SelectboxColumn(
                             "Talhão", options=[str(t) for t in talhoes_laudo], required=True)})
    try:
        proj = montar_projeto(laudo.dados, kmls, dict(zip(tab["Arquivo"], tab["Talhão"].astype(str))))
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível ligar os KMLs ao laudo: {e}")
        return
    for a in proj.avisos:
        st.warning(a)
    if not proj.talhoes:
        return
    st.dataframe(pd.DataFrame([{"Talhão": t.nome, "Área (ha)": round(t.area_ha, 2),
                                "Pontos ligados": len(t.amostras), "Amostras 20-40": len(t.sub),
                                "ha/ponto": round(t.area_ha / max(len(t.amostras), 1), 1)} for t in proj.talhoes]),
                 hide_index=True)
    for a in avisos_distancia(proj, laudo):
        st.warning(a)

    mapa_blocos = editor_blocos(proj, k0)

    d0 = laudo.dados
    with st.form(f"form_book_{k0}"):
        c1, c2, c3 = st.columns(3)
        marca = c1.radio("Book para", list(MARCAS), horizontal=True, index=list(MARCAS).index("Atria"))
        produtor = c2.text_input("Produtor", next((x for x in d0["proprietario"] if x), "").strip().title())
        propriedade = c3.text_input("Propriedade", next((x for x in d0["propriedade"] if x), "").strip().title())
        c4, c5, c6, c7 = st.columns(4)
        municipio = c4.text_input("Município (UF)", placeholder="ex.: Paraíso das Águas (MS)")
        data_coleta = c5.text_input("Data da coleta", placeholder="dd/mm/aaaa")
        safra = c6.text_input("Ano das prescrições", str(pd.Timestamp.today().year))
        subam = c7.number_input("Subamostras por ponto", 1, 50, 10)
        c8, c9 = st.columns(2)
        prod_cal = c8.text_input("Descrição do calcário",
                                 f"Calcário · {par.calcario.cao:g}% CaO; {par.calcario.mgo:g}% MgO; PRNT {par.calcario.prnt:g}")
        prod_ges = c9.text_input("Descrição do gesso", "Gesso agrícola · 19% Ca²⁺; 15% S")
        c10, c11, c12 = st.columns(3)
        chave_google = segredo("google_maps_key")
        opcoes = list(FONTES_SATELITE) + ["Sem imagem"]
        fonte = c10.selectbox("Imagem de satélite", opcoes,
                              index=0 if chave_google else opcoes.index("Esri World Imagery"),
                              help="Google exige a chave `google_maps_key` nos Secrets (Map Tiles API).")
        res_m = c11.select_slider("Tamanho do pixel (m)", [5, 10, 15, 20], value=10)
        n_zonas = c12.select_slider("Zonas por prescrição", [3, 4, 5, 6, 7, 8], value=6)
        st.markdown("**Fósforo e potássio nas prescrições**")
        c13, c14, c15 = st.columns(3)
        formula_book = c13.text_input(
            "Formulação fosfatada comprada (N-P₂O₅-K₂O)", ajustes.formula_p,
            placeholder="ex.: 11-52-00", help="As prescrições de fósforo saem em dose do PRODUTO. Sem formulação, "
                                              "o mapa mostra P₂O₅ (nutriente) e o shapefile de P₂O₅ fica bloqueado.")
        parc_book = c14.toggle("Parcelar KCl em 2 aplicações", ajustes.kcl_parcelado)
        pct_book = c15.slider("1ª aplicação do KCl (%)", 10, 90, int(ajustes.kcl_pct_1), 5)
        c16, c17 = st.columns(2)
        discreto = c16.checkbox("Mapas de fertilidade em faixas sólidas (1 cor por classe — melhor para impressão)",
                                value=True)
        ndvi = c17.checkbox("Incluir página de NDVI (Sentinel-2, últimos 12 meses)", value=True,
                            help="Vigor da vegetação por imagens de satélite gratuitas (Copernicus). "
                                 "Acrescenta cerca de 20–40 s na geração.")
        gerar = st.form_submit_button("🗺️ Gerar mapas, shapefiles e book", type="primary", width="stretch")

    chave_res = f"book_{k0}"
    if gerar and formula_book and not nome_produto_p(formula_book):
        st.error("Formulação fosfatada inválida. Use o formato 11-52-00.")
        gerar = False
    if gerar:
        ajustes = replace(ajustes, formula_p=formula_book.strip(), kcl_parcelado=parc_book,
                          kcl_pct_1=float(pct_book))
        barra = st.status("Gerando…", expanded=True)
        try:
            barra.write("Interpolando atributos (krigagem)…")
            mapas = superficies(proj, float(res_m))
            barra.write("Calculando doses por pixel e zonas de manejo…")
            calcular_doses(mapas, par, abertura, ajustes)
            blocos = gerar_todas_zonas(mapas, par, n_zonas, mapa_blocos)
            dados = DadosBook(marca=marca, produtor=produtor, propriedade=propriedade, municipio=municipio,
                              data_coleta=data_coleta, ano_safra=safra, subamostras=int(subam),
                              produto_calcario=prod_cal, produto_gesso=prod_ges,
                              fonte_satelite=None if fonte == "Sem imagem" else fonte,
                              laudo_numero=re.sub(r"\.(xlsx|xls|csv)$", "", nome_laudo, flags=re.I)[:60],
                              chave_google=chave_google, cores_discretas=discreto, incluir_ndvi=ndvi)
            with it.TRAVA_MPL:
                pdf, avisos = montar_book(proj, mapas, dados, par, ajustes, laudo.dados, progresso=barra.write,
                                          blocos=blocos)
            st.session_state[chave_res] = {
                "pdf": pdf, "mapas": mapas, "blocos": blocos, "epsg": proj.epsg, "avisos": avisos, "ajustes": ajustes,
                "volumes": tabela_volumes(mapas), "nome": f"{marca} - {propriedade or 'Book'}",
                "qualidade": pd.DataFrame([{"Talhão": m.talhao.nome, "Atributo": k, "Ajuste": aj.descricao(),
                                            "R² (validação cruzada)": round(aj.r2_cv, 2)}
                                           for m in mapas for k, aj in m.ajustes.items()])}
            barra.update(label="Pronto!", state="complete", expanded=False)
        except Exception as e:  # noqa: BLE001
            barra.update(label="Falhou", state="error")
            st.exception(e)

    r = st.session_state.get(chave_res)
    if r:
        for a in r["avisos"]:
            st.caption(f"⚠️ {a}")
        st.download_button("📕 Baixar book (PDF)", r["pdf"], file_name=f"Book - {r['nome']}.pdf",
                           mime="application/pdf", type="primary", width="stretch", key=f"dlb_{k0}")
        bloco_shapefiles(r, k0)
        v = r["volumes"].copy()
        if v["Produto"].str.startswith("Produto").any():
            v = v[v["Produto"] != "P2O5"]                  # com formulação, o volume é o do produto
        v["Área (ha)"] = v["Área (ha)"].round(2)
        v["Dose média (kg/ha)"] = v["Dose média (kg/ha)"].round(0)
        v["Total (t)"] = v["Total (t)"].round(2)
        st.markdown("##### Volumes de produto (pelos mapas de prescrição)")
        st.dataframe(v, hide_index=True, width="stretch")
        with st.expander("Detalhes da krigagem (uso interno — não vai para o book)"):
            st.dataframe(r["qualidade"], hide_index=True, width="stretch")


def fluxo_recomendacao():
    """Recomendação, interpretação e book a partir dos laudos."""
    arquivos = st.file_uploader("Laudo(s) de análise de solo", type=["xlsx", "xls", "csv"],
                                accept_multiple_files=True,
                                help="Pode anexar vários arquivos. Laudos da mesma fazenda são reconhecidos e podem ser "
                                     "juntados num só (recomendação e book únicos).")
    if not arquivos:
        return


    # --------------------------------------------- leitura e agrupamento por fazenda
    lidos, falhas = [], []
    for arq in arquivos:
        try:
            lidos.append((arq.name, ler_laudo_cache(arq.getvalue(), arq.name)))
        except Exception as e:  # noqa: BLE001
            falhas.append((arq.name, e))
    for nome, e in falhas:
        st.error(f"Não foi possível ler {nome}: {e}")
    if not lidos:
        return

    grupos = list(range(1, len(lidos) + 1))
    if len(lidos) > 1:
        sug = sugerir_grupos([l for _, l in lidos])
        ident = [identificacao(l) for _, l in lidos]
        n_juntos = len(sug) - len(set(sug))
        with st.expander(("🔗 Laudos da mesma fazenda reconhecidos — serão juntados" if n_juntos else
                          "🔗 Juntar laudos da mesma fazenda"), expanded=bool(n_juntos)):
            st.caption("Arquivos com o **mesmo número de grupo** viram um laudo só: uma planilha de recomendação, "
                       "uma interpretação e um book com todos os talhões. O grupo é sugerido pelo nome do produtor "
                       "e da propriedade; altere o número para juntar ou separar.")
            tab_g = st.data_editor(
                pd.DataFrame({"Arquivo": [n for n, _ in lidos], "Produtor": [a for a, _ in ident],
                              "Propriedade": [b for _, b in ident],
                              "Talhões": [len(set(l.dados["talhao"])) for _, l in lidos], "Grupo": sug}),
                hide_index=True, disabled=["Arquivo", "Produtor", "Propriedade", "Talhões"], key="grupos_laudos",
                column_config={"Grupo": st.column_config.NumberColumn("Grupo", min_value=1, max_value=len(lidos),
                                                                      step=1, required=True)})
            grupos = [int(g) for g in tab_g["Grupo"]]

    unidades = []                       # (nome exibido, nome base dos arquivos, laudo)
    for g in dict.fromkeys(grupos):
        membros = [lidos[i] for i in range(len(lidos)) if grupos[i] == g]
        if len(membros) == 1:
            nome, lau = membros[0]
            unidades.append((nome, re.sub(r"\.(xlsx|xls|csv)$", "", nome, flags=re.I), lau))
        else:
            lau, _ = juntar_laudos([l for _, l in membros], [n for n, _ in membros])
            prod, faz = identificacao(lau)
            base = (faz or prod or "Laudos juntados").strip().title()
            unidades.append((f"{len(membros)} laudos juntados · {base}", base, lau))

    for n_arq, (nome_arq, base_nome, laudo) in enumerate(unidades):
        st.divider()
        st.subheader(f"📄 {nome_arq}".replace("_", "\\_"))
        if getattr(laudo, "origens", None):
            st.caption("Arquivos: " + " · ".join(n for n, _ in laudo.origens))
        k0 = f"{n_arq}_{nome_arq}"

        n_sub = int(laudo.dados["subsuperficial"].sum())
        st.caption(f"{len(laudo.dados) - n_sub} amostras 0-20 cm"
                   + (f" · {n_sub} subsuperficiais (20-40 cm)" if n_sub else "") + f" · aba “{laudo.aba}”")
        for a in laudo.avisos:
            if "subsuperficial" not in a:
                st.warning(a)
        avisos_dados = getattr(laudo, "avisos_dados", None) or []
        if avisos_dados:
            st.info("**Dados ausentes no laudo**\n\n" + "\n".join(f"- {a}" for a in avisos_dados), icon="🔎")

        # --- abertura
        d0 = laudo.dados[~laudo.dados["subsuperficial"]]
        talhoes = list(dict.fromkeys(d0["talhao"]))
        st.markdown("**Marque os talhões que são área de abertura** (dose de calcário × "
                    f"{par.calcario.fator_abertura:g})")
        edit = st.data_editor(
            pd.DataFrame({"Talhão": talhoes, "Abertura": [False] * len(talhoes),
                          "Amostras 0-20": [int((d0["talhao"] == t).sum()) for t in talhoes]}),
            hide_index=True, disabled=["Talhão", "Amostras 0-20"], key=f"ab_{k0}",
            column_config={"Abertura": st.column_config.CheckboxColumn("Área de abertura?")},
        )
        abertura = dict(zip(edit["Talhão"], edit["Abertura"]))

        # --- ajustes (médias pela regra vêm de um cálculo sem ajustes)
        base = recomendar(laudo, par, abertura)
        b0 = base[~base[COL_SUB]]
        with st.expander("⚙️ Ajustar doses · volume já comprado · formulação de P · S elementar · parcelamento de KCl",
                         expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            aj_cal = bloco_ajuste(c1, "Calcário", b0[COL_CAL].mean(), f"{k0}_cal", "calcário")
            s0 = st.session_state.get(f"{k0}_s0", False)
            if s0:
                tmp = recomendar(laudo, par, abertura, Ajustes(gesso_por_s_elementar=True))
                media_g, nome_g = tmp.loc[~tmp[COL_SUB], COL_S0].mean(), "S elementar"
            else:
                media_g, nome_g = b0[COL_GES].mean(), "gesso"
            aj_ges = bloco_ajuste(
                c2, "Gesso / S elementar", media_g, f"{k0}_{'s0aj' if s0 else 'ges'}", nome_g,
                antes=lambda: st.toggle("Substituir por S elementar", key=f"{k0}_s0",
                                        help="S elementar (kg/ha) = 4,1904 × (dose de gesso)^0,3754"))
            aj_p = bloco_ajuste(c3, "P2O5", b0[COL_P].mean(), f"{k0}_p", "fósforo (em P2O5)")
            with c3:
                formula = st.text_input("Formulação do produto (N-P2O5-K2O)", key=f"{k0}_form",
                                        placeholder="ex.: 11-52-00, 00-46-00, 02-22-00")
                if formula and not nome_produto_p(formula):
                    st.error("Formulação inválida. Use o formato 11-52-00.")
                elif formula:
                    fl = ler_formula(formula)
                    st.caption(f"Produto com {fl[1]:g}% de P2O5 → dose = P2O5 ÷ {fl[1] / 100:g}")
            aj_k = bloco_ajuste(c4, "KCl", b0[COL_K].mean(), f"{k0}_k", "KCl")
            with c4:
                parcelar = st.toggle("Parcelar em 2 aplicações", key=f"{k0}_parc",
                                     help="Indicado para solos arenosos, para reduzir perdas de K. "
                                          "As duas parcelas somam a dose total recomendada.")
                pct1 = 50.0
                if parcelar:
                    pct1 = float(st.slider("1ª aplicação (% da dose)", 10, 90, 50, 5, key=f"{k0}_pct1"))
                    st.caption(f"1ª aplicação: **{pct1:.0f}%** · 2ª aplicação: **{100 - pct1:.0f}%**")

        ajustes = Ajustes(calcario=aj_cal, gesso=aj_ges, p2o5=aj_p, kcl=aj_k,
                          gesso_por_s_elementar=s0, formula_p=formula or "",
                          kcl_parcelado=parcelar, kcl_pct_1=pct1)
        res = recomendar(laudo, par, abertura, ajustes)
        rec = res[~res[COL_SUB]]
        doses = colunas_doses(res)
        doses_totais = colunas_doses_totais(res)

        d1, d2 = st.columns(2)
        # arquivos gerados só no clique (não a cada interação na tela)
        d1.download_button("⬇️ Baixar recomendações (Excel)",
                           data=adiado(gerar_excel, res, laudo, par, nome_arq, ajustes),
                           file_name=f"Recomendacao - {base_nome}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", key=f"dl_{k0}", width="stretch")
        d2.download_button("📊 Baixar interpretação por talhão (Excel)",
                           data=adiado(gerar_excel_interpretacao, res, laudo, nome_arq),
                           file_name=f"Interpretacao - {base_nome}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"dli_{k0}", width="stretch")

        aba_rec, aba_int, aba_book = st.tabs(["📋 Recomendações", "📊 Interpretação por talhão", "📚 Montar book"])

        with aba_rec:
            cols = st.columns(len(doses_totais))
            for col, nome in zip(cols, doses_totais):
                s = rec[nome].dropna()
                info = res.attrs["ajustes"].get(
                    {COL_CAL: "Calcário", COL_GES: "Gesso", COL_S0: "S elementar", COL_P: "P2O5",
                     COL_K: "KCl"}.get(nome, "Produto P"), {})
                delta = None
                a = info.get("ajuste")
                if a is not None and a.ativo() and info.get("media_regra"):
                    delta = f"{(info['fator'] - 1) * 100:+.0f}% vs. regra"
                col.metric(nome.replace(" (kg/ha)", "") + " · média",
                           f"{br(s.mean())} kg/ha" if len(s) else "—", delta=delta, delta_color="off",
                           help=f"Faixa: {br(s.min())}–{br(s.max())} kg/ha" if len(s) else None)

            if COL_K1 in res:
                st.caption(f"KCl parcelado: 1ª aplicação {pct1:.0f}% (média {br(rec[COL_K1].mean())} kg/ha) + "
                           f"2ª aplicação {100 - pct1:.0f}% (média {br(rec[COL_K1.replace('1ª', '2ª')].mean())} kg/ha)")
            vis = ["N Lab", "Identificação", "Talhão", "Profundidade (cm)", "Abertura"] + doses + ["Observações"]
            st.dataframe(estilo_linhas(res[vis], res[COL_SUB]), hide_index=True, width="stretch",
                         height=min(38 + 35 * len(res), 560))
            if n_sub:
                st.markdown(f'<span class="sub-legenda"></span>Amostras de 20-40 cm: exibidas para '
                            'consulta, mas <b>fora do cálculo e da planilha de saída</b>.',
                            unsafe_allow_html=True)

        with aba_int:
            medias = it.medias_por_talhao(laudo)
            if medias.empty:
                st.info("Sem amostras de 0-20 cm para interpretar.")
            else:
                st.markdown("##### Situação por talhão (camada 0-20 cm)")
                st.image(png_interpretacao("mapa", medias), width="stretch")
                st.markdown("##### Pontos de atenção")
                for t, itens in it.pontos_de_atencao(medias).items():
                    txt = ", ".join(itens) if itens else "sem atributos em classe baixa ou crítica"
                    st.markdown(f"- **{t}** ({medias.set_index('Talhão').loc[t, 'Textura'].lower()}): {txt}")
                st.markdown("##### Panorama da fertilidade")
                st.caption("Média de cada talhão sobre a escala de 8 classes (mais à direita = melhor condição; "
                           "↓ = atributo em que valores menores são melhores).")
                st.image(png_interpretacao("panorama", medias), width="stretch")
                st.markdown("##### Distribuição das amostras por classe")
                st.image(png_interpretacao("classes", laudo.dados), width="stretch")
                if all(c in medias for c in ("ca", "mg", "k", "hal")):
                    st.markdown("##### Equilíbrio de bases")
                    st.image(png_interpretacao("bases", medias, 100 * par.calcario.alvo_ca, 100 * par.calcario.alvo_mg),
                             width="stretch")
                st.markdown("##### Doses médias recomendadas por talhão")
                st.image(png_interpretacao("doses", sem_attrs(res), tuple(doses_totais)), width="stretch")
                medias_sub = it.medias_por_talhao(laudo, subsuperficial=True)
                if not medias_sub.empty:
                    st.markdown("##### Camada subsuperficial (20-40 cm) — informativa")
                    st.image(png_interpretacao("mapa", medias_sub), width="stretch")

        with aba_book:
            aba_montar_book(laudo, par, abertura, ajustes, k0, nome_arq)


def em_desenvolvimento(icone: str, titulo: str, texto: str) -> None:
    st.markdown(f"### {icone} {titulo}")
    st.info("**Em desenvolvimento =)**", icon="🚧")
    st.caption(texto)


# ------------------------------------------------------------------ abas
aba_rec, aba_comp, aba_sat, aba_sem = st.tabs(["🧪 Recomendação e book", "📈 Comparações", "🛰️ Satélites",
                                               "🌱 Mapa de Sementes"])
with aba_comp:
    em_desenvolvimento("📈", "Comparações entre safras",
                       "Upload de laudos de dois anos da mesma área para gerar um book comparativo "
                       "(evolução dos atributos, mapas de diferença e efeito das aplicações).")
with aba_sat:
    em_desenvolvimento("🛰️", "Satélites",
                       "Avaliações e mapas a partir de imagens de satélite (índices de vegetação, séries "
                       "temporais, zonas de manejo).")
with aba_sem:
    em_desenvolvimento("🌱", "Mapa de Sementes",
                       "Mapas de semeadura em taxa variável a partir dos atributos químicos do solo.")
with aba_rec:
    fluxo_recomendacao()
