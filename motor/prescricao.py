"""Mapas de atributos e de prescrição por talhão (pixel → zonas → shapefile)."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import shapefile  # pyshp
from scipy import ndimage
from shapely import box, union_all
from shapely.geometry import MultiPolygon, Polygon, mapping

from . import regras
from .geo import Projeto, Talhao, projetar
from .interpretacao import completar_derivados
from .krigagem import Ajuste, Grade, grade_do_poligono, interpolar_grade
from .parametros import Ajustes, Parametros

ATRIB_MAPA = ["ph", "mo", "ctc", "v", "hal", "al", "m", "ca", "sat_ca", "mg", "sat_mg", "k", "sat_k",
              "p", "s", "b", "zn", "mn", "cu", "fe", "argila", "silte", "areia"]
BASE_DOSE = ["ca", "mg", "hal", "al", "k", "p", "s", "argila"]
WGS84_PRJ = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


@dataclass
class MapaTalhao:
    talhao: Talhao
    grade: Grade
    atributos: dict[str, np.ndarray] = field(default_factory=dict)
    ajustes: dict[str, Ajuste] = field(default_factory=dict)
    doses: dict[str, np.ndarray] = field(default_factory=dict)      # produto → pixels (kg/ha)
    zonas: dict[str, "Zonas"] = field(default_factory=dict)


@dataclass
class Zonas:
    produto: str
    niveis: list[float]
    poligonos: list[tuple[float, Polygon | MultiPolygon]]    # (dose, geometria UTM)
    classes: np.ndarray                                     # raster de classes (−1 fora)

    def tabela(self) -> pd.DataFrame:
        linhas = [{"Dose (kg/ha)": d, "Área (ha)": g.area / 1e4} for d, g in self.poligonos]
        t = pd.DataFrame(linhas).groupby("Dose (kg/ha)", as_index=False).sum()
        t["Produto (kg)"] = t["Dose (kg/ha)"] * t["Área (ha)"]
        return t

    @property
    def area_ha(self) -> float:
        return sum(g.area for _, g in self.poligonos) / 1e4

    @property
    def total_kg(self) -> float:
        return sum(d * g.area / 1e4 for d, g in self.poligonos)

    @property
    def dose_media(self) -> float:
        return self.total_kg / self.area_ha if self.area_ha else float("nan")


# ------------------------------------------------------------- superfícies
def superficies(projeto: Projeto, res: float = 10.0, atributos=None) -> list[MapaTalhao]:
    atributos = atributos or ATRIB_MAPA
    mapas = []
    for t in projeto.talhoes:
        g = grade_do_poligono(t.perimetro, res)
        a = completar_derivados(t.amostras)
        m = MapaTalhao(t, g)
        for k in dict.fromkeys(list(atributos) + BASE_DOSE):
            if k in a and a[k].notna().sum() > 0:
                m.atributos[k], m.ajustes[k] = interpolar_grade(g, a["x"], a["y"], a[k])
        mapas.append(m)
    return mapas


# ------------------------------------------------------------------ doses
def _vetor(fun, *arrs, **kw):
    out = np.full(arrs[0].shape, np.nan)
    ok = np.all([np.isfinite(a) for a in arrs], axis=0)
    it = zip(*[a[ok] for a in arrs])
    out[ok] = [(fun(*v, **kw).dose or np.nan) for v in it]
    return out


def calcular_doses(mapas: list[MapaTalhao], par: Parametros, abertura: dict[str, bool],
                   aj: Ajustes) -> dict[str, float]:
    """Doses por pixel com as mesmas regras e ajustes da planilha. Devolve os fatores aplicados."""
    for m in mapas:
        A = m.atributos
        zero = np.zeros_like(A["ca"])
        ab = bool(abertura.get(m.talhao.nome, abertura.get(m.talhao.chave, False)))
        m.doses = {
            "Calcário": _vetor(lambda ca, mg, hal, al, k: regras.calcario(ca, mg, hal, al, k, ab, par.calcario),
                               A["ca"], A["mg"], A["hal"], A.get("al", zero), A.get("k", zero)),
            "Gesso": _vetor(lambda s, arg: regras.gesso(s, arg, par.gesso), A["s"], A["argila"]),
            "P2O5": _vetor(lambda p: regras.p2o5(p, par.fosforo), A["p"]),
            "KCl": _vetor(lambda k: regras.kcl(k, par.potassio), A["k"]),
        }
        if aj.gesso_por_s_elementar:
            g = m.doses.pop("Gesso")
            m.doses["S elementar"] = np.where(np.isfinite(g), par.enxofre.coef * np.power(g, par.enxofre.expoente),
                                              np.nan)

    fatores = {}
    pares = [("Calcário", aj.calcario), ("S elementar" if aj.gesso_por_s_elementar else "Gesso", aj.gesso),
             ("P2O5", aj.p2o5), ("KCl", aj.kcl)]
    for nome, a in pares:
        todos = np.concatenate([m.doses[nome][m.grade.mascara] for m in mapas])
        media = np.nanmean(todos)             # pixels têm a mesma área → média ponderada pela área
        f = (a.media_alvo / media) if (a.media_alvo is not None and media > 0) else (1 + a.pct / 100)
        fatores[nome] = f
        for m in mapas:
            m.doses[nome] = m.doses[nome] * f

    form = regras.ler_formula(aj.formula_p)
    for m in mapas:
        if form and form[1] > 0:
            m.doses[f"Produto {int(form[0]):02d}-{int(form[1]):02d}-{int(form[2]):02d}"] = \
                m.doses["P2O5"] / (form[1] / 100)
        if aj.kcl_parcelado:
            m.doses["KCl 1ª aplicação"] = m.doses["KCl"] * aj.kcl_pct_1 / 100
            m.doses["KCl 2ª aplicação"] = m.doses["KCl"] * (100 - aj.kcl_pct_1) / 100
    return fatores


def passo_arredondamento(produto: str, par: Parametros) -> int:
    a = par.arredondamento
    for prefixo, passo in (("Calcário", a.calcario), ("Gesso", a.gesso), ("S elementar", a.s_elementar),
                           ("P2O5", a.p2o5), ("Produto", a.produto_p), ("KCl", a.kcl)):
        if produto.startswith(prefixo):
            return passo
    return 1


# ------------------------------------------------------------------ zonas
def _suavizar_nan(D, mascara, sigma):
    V = np.where(mascara, np.nan_to_num(D), 0.0)
    W = mascara.astype(float)
    num = ndimage.gaussian_filter(V, sigma)
    den = ndimage.gaussian_filter(W, sigma)
    out = np.where(mascara & (den > 1e-6), num / np.maximum(den, 1e-6), np.nan)
    return out


def _peneira(C, mascara, min_px):
    """Remove manchas pequenas: cada mancha < min_px assume a classe vizinha mais comum."""
    C = C.copy()
    for _ in range(3):
        mudou = False
        for k in np.unique(C[mascara]):
            lab, n = ndimage.label((C == k) & mascara)
            if n == 0:
                continue
            tam = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
            for i in np.where(tam < min_px)[0] + 1:
                reg = lab == i
                borda = ndimage.binary_dilation(reg) & ~reg & mascara
                viz = C[borda]
                if viz.size:
                    C[reg] = np.bincount(viz).argmax()
                    mudou = True
        if not mudou:
            break
    return C


def _preencher_fora(D, mascara):
    """Estende os valores para fora do talhão (vizinho mais próximo) para o contorno não 'grudar' na borda."""
    idx = ndimage.distance_transform_edt(~mascara, return_distances=False, return_indices=True)
    return D[tuple(idx)]


def _regiao_acima(g: Grade, campo, limiar):
    """Polígono (UTM) da região onde campo ≥ limiar, com bordas suaves (curva de contorno)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.geometry import Polygon as P
    r = g.res
    # moldura com valor baixo para fechar as curvas na borda da grade
    pad = np.pad(campo, 1, constant_values=np.nanmin(campo) - 1)
    xs = np.concatenate([[g.x[0] - r], g.x, [g.x[-1] + r]])
    ys = np.concatenate([[g.y[0] + r], g.y, [g.y[-1] - r]])
    fig, ax = plt.subplots()
    cs = ax.contourf(xs, ys, pad, levels=[limiar, np.inf])
    reg = Polygon()
    for path in cs.get_paths():
        for anel in path.to_polygons(closed_only=True):
            if len(anel) >= 4:
                reg = reg.symmetric_difference(P(anel).buffer(0))   # regra par-ímpar (trata furos)
    plt.close(fig)
    return reg.buffer(0)


def _dose_suave(m: MapaTalhao, produto: str, suavizacao_m: float = 25.0):
    g, D = m.grade, m.doses[produto]
    mask = g.mascara & np.isfinite(D)
    return _suavizar_nan(D, mask, sigma=max(suavizacao_m / g.res, 1.0)), mask


def niveis_de_dose(lo: float, hi: float, n_zonas: int, passo: float) -> list[float]:
    """n_zonas doses igualmente espaçadas entre lo e hi, arredondadas (refina o passo se a faixa é estreita)."""
    niveis = []
    for p in (passo, 1, 0.5, 0.1):
        niveis = sorted(set(regras.arredondar(v, p) if p >= 1 else round(v, 1) for v in np.linspace(lo, hi, n_zonas)))
        if len(niveis) >= n_zonas:
            break
    return niveis


def gerar_zonas(m: MapaTalhao, produto: str, n_zonas: int = 6, passo: int = 1,
                area_min_ha: float = 0.5, largura_min_m: float = 30.0, suavizacao_m: float = 25.0,
                niveis: list[float] | None = None) -> Zonas:
    """Zonas de manejo aplicáveis: suavização de ~25 m, faixas com pelo menos `largura_min_m`
    (largura de aplicação) e áreas de pelo menos `area_min_ha`.

    `niveis`: doses já definidas (blocos de talhões usam as mesmas doses em todos os talhões)."""
    g, D = m.grade, m.doses[produto]
    Ds, mask = _dose_suave(m, produto, suavizacao_m)
    if niveis is None:
        niveis = niveis_de_dose(np.nanmin(Ds[mask]), np.nanmax(Ds[mask]), n_zonas, passo)
    niveis = list(niveis)
    niv = np.array(niveis, float)
    C = np.full(D.shape, -1, int)
    C[mask] = np.abs(Ds[mask][:, None] - niv[None, :]).argmin(axis=1)
    min_px = max(1, int(area_min_ha / g.area_pixel_ha))
    C[mask] = _peneira(np.where(mask, C, 0), mask, min_px)[mask]

    # regiões encaixadas R_k = {dose suavizada ≥ limiar_k} traçadas por curvas de contorno;
    # zona k = R_k − R_{k+1} (partição exata do perímetro, sem sobreposição nem buraco)
    per = m.talhao.perimetro
    campo = _preencher_fora(Ds, mask)
    limiares = [(niv[k - 1] + niv[k]) / 2 for k in range(1, len(niv))]
    regioes = [per]
    r_ab = largura_min_m / 2
    for t in limiares:
        reg = _regiao_acima(g, campo, t)
        if r_ab > 0 and not reg.is_empty:          # abertura morfológica: remove faixas/anéis estreitos
            reg = reg.buffer(-r_ab, join_style="round").buffer(r_ab, join_style="round")
        reg = reg.intersection(per)
        regioes.append(reg.intersection(regioes[-1]).buffer(0))
    polys = []
    for k, dose in enumerate(niv):
        z = regioes[k].difference(regioes[k + 1]) if k + 1 < len(regioes) else regioes[k]
        if not z.is_empty:
            partes = list(z.geoms) if hasattr(z, "geoms") else [z]
            for p in partes:
                if isinstance(p, Polygon) and p.area > 0.01:
                    polys.append((float(dose), p))
    return Zonas(produto, niveis, _fundir_pequenos(polys, area_min_ha * 1e4), C)


def _fundir_pequenos(polys, area_min):
    """Funde cada polígono menor que area_min ao vizinho com maior divisa comum."""
    polys = [[d, p] for d, p in polys]
    while True:
        polys.sort(key=lambda t: t[1].area)
        alvo = next((i for i, (_, p) in enumerate(polys) if p.area < area_min), None)
        if alvo is None or len(polys) < 2:
            break
        d0, p0 = polys.pop(alvo)
        melhor, comp = None, 0.0
        for j, (_, q) in enumerate(polys):
            if p0.distance(q) < 0.5:
                c = p0.buffer(0.5).intersection(q.boundary).length
                if c > comp:
                    melhor, comp = j, c
        if melhor is None:            # isolado (não encosta em ninguém): mantém
            polys.append([d0, p0])
            if all(p.area >= area_min or p is p0 for _, p in polys):
                break
            continue
        polys[melhor][1] = polys[melhor][1].union(p0).buffer(0)     # mantém todas as partes (sem perda de área)
    # junta polígonos de mesma dose que se tocam
    saida = []
    for dose in sorted({d for d, _ in polys}):
        u = union_all([p for d, p in polys if d == dose])
        for p in (u.geoms if hasattr(u, "geoms") else [u]):
            if isinstance(p, Polygon) and not p.is_empty:
                saida.append((dose, p))
    return saida


@dataclass
class Bloco:
    """Bloco de aplicação: um ou mais talhões com prescrição e shapefile únicos por produto."""
    nome: str
    mapas: list[MapaTalhao]
    zonas: dict[str, Zonas] = field(default_factory=dict)

    @property
    def unico(self) -> bool:
        return len(self.mapas) == 1

    @property
    def perimetro(self):
        return union_all([m.talhao.perimetro for m in self.mapas])

    @property
    def talhoes(self) -> list[str]:
        return [m.talhao.nome for m in self.mapas]


def _juntar_zonas(produto: str, niveis, lista: list[Zonas]) -> Zonas:
    """Zonas de vários talhões num só conjunto: um registro (multipolígono) por dose."""
    polys = []
    for dose in sorted({d for z in lista for d, _ in z.poligonos}):
        u = union_all([g for z in lista for d, g in z.poligonos if d == dose])
        if not u.is_empty:
            polys.append((dose, u))
    return Zonas(produto, list(niveis), polys, None)


def gerar_todas_zonas(mapas: list[MapaTalhao], par: Parametros, n_zonas: int = 6,
                      blocos: dict[str, str] | None = None) -> list[Bloco]:
    """Zonas de todos os talhões. `blocos`: talhão → nome do bloco (talhões com o mesmo nome são
    prescritos juntos: mesmas doses e um shapefile por produto). Talhão sem bloco = separado.
    Devolve a lista de blocos (um por talhão separado)."""
    blocos = {k: v.strip() for k, v in (blocos or {}).items() if v and str(v).strip()}
    grupos: dict[str, list[MapaTalhao]] = {}
    for m in mapas:
        chave = blocos.get(m.talhao.nome) or blocos.get(m.talhao.chave)
        grupos.setdefault(chave or f"\0{m.talhao.nome}", []).append(m)
    saida = []
    for chave, ms in grupos.items():
        for m in ms:
            m.zonas = {}
        if len(ms) == 1:
            m = ms[0]
            for prod in m.doses:
                m.zonas[prod] = gerar_zonas(m, prod, n_zonas, passo_arredondamento(prod, par))
            saida.append(Bloco(m.talhao.nome, ms, m.zonas))
            continue
        b = Bloco(chave, ms)
        for prod in ms[0].doses:
            suaves = [_dose_suave(m, prod) for m in ms]
            vals = np.concatenate([Ds[mk] for Ds, mk in suaves])
            vals = vals[np.isfinite(vals)]
            if not len(vals):
                continue
            niv = niveis_de_dose(vals.min(), vals.max(), n_zonas, passo_arredondamento(prod, par))
            for m in ms:
                m.zonas[prod] = gerar_zonas(m, prod, n_zonas, niveis=niv)
            b.zonas[prod] = _juntar_zonas(prod, niv, [m.zonas[prod] for m in ms])
        saida.append(b)
    return saida


# -------------------------------------------------------------- shapefiles
def _nome_arquivo(txt: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t).strip("_").replace("__", "_")


def shapefile_bytes(zonas: Zonas, epsg: int, nome: str) -> dict[str, bytes]:
    """Shapefile (WGS84, campo Taxa_Dest_) no mesmo formato do arquivo de referência."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    w.field("Taxa_Dest_", "N", size=15, decimal=4)
    for dose, geom in sorted(zonas.poligonos, key=lambda t: -t[0]):
        ll = projetar(geom, epsg, inverso=True)
        partes = []
        for p in (ll.geoms if hasattr(ll, "geoms") else [ll]):
            ext = list(p.exterior.coords)
            if Polygon(ext).exterior.is_ccw:
                ext = ext[::-1]                         # anel externo horário (padrão shapefile)
            partes.append(ext)
            for furo in p.interiors:
                f = list(furo.coords)
                partes.append(f if Polygon(f).exterior.is_ccw else f[::-1])
        w.poly(partes)
        w.record(round(dose, 4))
    w.close()
    return {f"{nome}.shp": shp.getvalue(), f"{nome}.shx": shx.getvalue(),
            f"{nome}.dbf": dbf.getvalue(), f"{nome}.prj": WGS84_PRJ.encode()}


def zip_prescricoes(mapas: list[MapaTalhao], epsg: int, fazenda: str = "",
                    produtos: list[str] | None = None) -> bytes:
    """Zip com uma pasta por talhão (ou por bloco) e um shapefile por produto (todos, ou só os de `produtos`).

    `mapas`: lista de MapaTalhao ou de Bloco."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for m in mapas:
            rotulo = m.talhao.nome if isinstance(m, MapaTalhao) else m.nome
            pasta = _nome_arquivo(rotulo)
            for prod, zon in m.zonas.items():
                if produtos is not None and prod not in produtos:
                    continue
                nome = _nome_arquivo(f"{prod}_{rotulo}")
                for arq, dados in shapefile_bytes(zon, epsg, nome).items():
                    z.writestr(f"{pasta}/{nome}/{arq}", dados)
    return buf.getvalue()


def tabela_volumes(mapas: list[MapaTalhao]) -> pd.DataFrame:
    linhas = []
    for m in mapas:
        for prod, zon in m.zonas.items():
            linhas.append({"Talhão": m.talhao.nome, "Área (ha)": zon.area_ha, "Produto": prod,
                           "Dose média (kg/ha)": zon.dose_media, "Total (t)": zon.total_kg / 1000})
    return pd.DataFrame(linhas)
