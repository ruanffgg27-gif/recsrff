"""Leitura de KML/KMZ, projeção e ligação dos pontos amostrais com o laudo."""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import transform, unary_union


# ------------------------------------------------------------------ KML/KMZ
def _txt_kml(conteudo: bytes, nome: str) -> str:
    if nome.lower().endswith(".kmz") or conteudo[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            kml = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
            if not kml:
                raise ValueError(f"{nome}: KMZ sem arquivo .kml dentro")
            conteudo = z.read(kml)
    for enc in ("utf-8", "latin-1"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", "ignore")


def _sem_ns(txt: str) -> ET.Element:
    txt = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", txt, count=0)
    txt = re.sub(r"<(/?)\w+:", r"<\1", txt)          # remove prefixos (gx:, kml:, atom:)
    txt = re.sub(r"\s\w+:(\w+=)", r" \1", txt)        # atributos com prefixo
    return ET.fromstring(txt.encode("utf-8"))


def _coords(txt: str) -> list[tuple[float, float]]:
    pts = []
    for trio in (txt or "").split():
        partes = trio.split(",")
        if len(partes) >= 2:
            pts.append((float(partes[0]), float(partes[1])))
    return pts


def _conserta(t: str) -> str:
    """Corrige texto duplamente codificado ('JoÃ£o' → 'João')."""
    if "Ã" in t or "Â" in t:
        try:
            return t.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return t
    return t


def _dados_extras(pm: ET.Element) -> dict:
    d = {}
    for sd in pm.iter("SimpleData"):
        d[sd.get("name")] = _conserta((sd.text or "").strip())
    for dd in pm.iter("Data"):
        v = dd.find("value")
        d[dd.get("name")] = (v.text or "").strip() if v is not None else ""
    return d


@dataclass
class ArquivoKML:
    nome: str
    pontos: pd.DataFrame            # colunas: nome, lon, lat, ordem
    poligonos: list[Polygon]
    atributos: dict = field(default_factory=dict)

    @property
    def tipo(self) -> str:
        if self.poligonos and not len(self.pontos):
            return "perimetro"
        if len(self.pontos) and not self.poligonos:
            return "pontos"
        return "misto" if len(self.pontos) else "vazio"


def ler_kml(conteudo: bytes, nome: str) -> ArquivoKML:
    raiz = _sem_ns(_txt_kml(conteudo, nome))
    pontos, polys, attrs = [], [], {}
    for i, pm in enumerate(raiz.iter("Placemark")):
        nm = (pm.findtext("name") or "").strip()
        extra = _dados_extras(pm)
        for pt in pm.iter("Point"):
            c = _coords(pt.findtext("coordinates"))
            if c:
                pontos.append({"nome": nm or extra.get("ID Recurso", ""), "lon": c[0][0], "lat": c[0][1],
                               "ordem": len(pontos) + 1})
        for pg in pm.iter("Polygon"):
            ext = _coords(pg.findtext("outerBoundaryIs/LinearRing/coordinates"))
            furos = [_coords(r.findtext("coordinates")) for r in pg.findall("innerBoundaryIs/LinearRing")]
            if len(ext) >= 3:
                p = Polygon(ext, [f for f in furos if len(f) >= 3])
                polys.append(p if p.is_valid else p.buffer(0))
                attrs.update(extra)
    return ArquivoKML(nome, pd.DataFrame(pontos, columns=["nome", "lon", "lat", "ordem"]), polys, attrs)


def numero_talhao(texto: str) -> str | None:
    """'Pontos_TH_1_Campo_Verde.kml' → '1'; 'Th_02' → '2'; 'Talhão 3' → '3'."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    m = re.search(r"(?:th|talhao|tal|gleba|field)[\s_\-\.]*0*(\d+)", t)
    return m.group(1) if m else None


def chave_talhao(v) -> str:
    """Normaliza o nome do talhão do laudo para comparação ('1', '1.0', 'TH 01' → '1')."""
    s = str(v).strip()
    try:
        f = float(s.replace(",", "."))
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    n = numero_talhao(s)
    return n if n else s.upper()


# ----------------------------------------------------------------- projeção
def epsg_utm_sirgas(lon: float, lat: float) -> int:
    zona = int((lon + 180) // 6) + 1
    return (31960 + zona) if lat < 0 else (31954 + zona)   # SIRGAS 2000 / UTM zona S (Brasil)


def projetar(geom, epsg: int, inverso: bool = False):
    t = Transformer.from_crs(4326 if not inverso else epsg, epsg if not inverso else 4326, always_xy=True)
    return transform(t.transform, geom)


def xy_de(lon, lat, epsg: int):
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    return t.transform(np.asarray(lon), np.asarray(lat))


# ------------------------------------------------------ talhões e amostras
@dataclass
class Talhao:
    chave: str                      # '1', '2', ...
    nome: str                       # como aparece no laudo/book
    perimetro_ll: Polygon | MultiPolygon          # lon/lat
    perimetro: Polygon | MultiPolygon             # UTM (m)
    amostras: pd.DataFrame          # linhas 0-20 do laudo + x, y, lon, lat, ponto
    sub: pd.DataFrame               # linhas 20-40 com coordenadas do ponto correspondente
    avisos: list[str] = field(default_factory=list)

    @property
    def area_ha(self) -> float:
        return self.perimetro.area / 10_000


@dataclass
class Projeto:
    epsg: int
    talhoes: list[Talhao]
    avisos: list[str]

    @property
    def area_total(self) -> float:
        return sum(t.area_ha for t in self.talhoes)


def _num_ponto(nome: str, ordem: int) -> int:
    m = re.search(r"\d+", str(nome))
    return int(m.group()) if m else ordem


def _num_amostra(ident: str) -> int | None:
    m = re.findall(r"\d+", str(ident))
    return int(m[-1]) if m else None


def montar_projeto(dados_laudo: pd.DataFrame, kmls: list[ArquivoKML],
                   atribuicao: dict[str, str] | None = None) -> Projeto:
    """Liga laudo + KMLs.

    dados_laudo: `Laudo.dados` (com colunas talhao, identificacao, subsuperficial…).
    atribuicao: {nome do arquivo KML: chave do talhão} para forçar a associação.
    Regra de ligação: dentro de cada talhão, as amostras 0-20 do laudo, na ordem
    em que aparecem, correspondem aos pontos 1..n do KML. Amostras 20-40 herdam o
    ponto da amostra de mesmo número (mesmo local, outra camada).
    """
    atribuicao = atribuicao or {}
    avisos: list[str] = []
    d = dados_laudo.copy()
    d["_tal"] = d["talhao"].apply(chave_talhao)
    perims: dict[str, list] = {}
    pontos: dict[str, ArquivoKML] = {}
    for k in kmls:
        chave = atribuicao.get(k.nome) or numero_talhao(k.nome) or numero_talhao(k.atributos.get("Field", ""))
        if chave is None:
            avisos.append(f"{k.nome}: não identifiquei o talhão pelo nome do arquivo")
            continue
        if k.poligonos:
            perims.setdefault(chave, []).extend(k.poligonos)
        if len(k.pontos):
            if chave in pontos:
                avisos.append(f"Talhão {chave}: mais de um arquivo de pontos; usei {pontos[chave].nome}")
            else:
                pontos[chave] = k

    todos = [g for gs in perims.values() for g in gs] or \
            [Point(r.lon, r.lat) for k in pontos.values() for r in k.pontos.itertuples()]
    if not todos:
        raise ValueError("Nenhum perímetro ou ponto encontrado nos KMLs")
    c = unary_union(todos).centroid
    epsg = epsg_utm_sirgas(c.x, c.y)

    talhoes = []
    ordem_laudo = list(dict.fromkeys(d["_tal"]))
    for chave in ordem_laudo:
        av: list[str] = []
        rows = d[d["_tal"] == chave]
        sup = rows[~rows["subsuperficial"]].reset_index(drop=True)
        sub = rows[rows["subsuperficial"]].reset_index(drop=True)
        nome = next((str(v) for v in rows["talhao"] if str(v).strip()), chave)
        nome = f"Talhão {chave}" if nome.replace(".0", "").isdigit() else nome
        if chave not in perims:
            avisos.append(f"{nome}: sem KML de perímetro — talhão fora dos mapas")
            continue
        per_ll = unary_union(perims[chave])
        per = projetar(per_ll, epsg)
        if chave in pontos:
            pk = pontos[chave].pontos.copy()
            pk["n"] = [_num_ponto(a, b) for a, b in zip(pk["nome"], pk["ordem"])]
            pk = pk.sort_values("n").reset_index(drop=True)
        else:
            pk = pd.DataFrame(columns=["nome", "lon", "lat", "ordem", "n"])
            av.append("sem KML de pontos")
        if len(pk) != len(sup):
            av.append(f"laudo tem {len(sup)} amostras 0-20 e o KML tem {len(pk)} pontos — "
                      f"liguei os {min(len(pk), len(sup))} primeiros")
        m = min(len(pk), len(sup))
        sup = sup.iloc[:m].copy()
        sup["ponto"] = pk["n"].values[:m]
        sup["lon"] = pk["lon"].values[:m].astype(float)
        sup["lat"] = pk["lat"].values[:m].astype(float)
        if m:
            sup["x"], sup["y"] = xy_de(sup["lon"], sup["lat"], epsg)
            fora = [int(p) for p, xx, yy in zip(sup["ponto"], sup["x"], sup["y"])
                    if not per.buffer(30).contains(Point(xx, yy))]
            if fora:
                av.append(f"ponto(s) {fora} fora do perímetro — confira se os arquivos são do mesmo talhão")
        # 20-40: mesmo local da amostra de mesmo número
        for c2 in ("ponto", "lon", "lat", "x", "y"):
            if c2 not in sub:
                sub[c2] = pd.Series(dtype=float)
        if len(sub):
            sub = sub.copy()
            numeros = sup.assign(_num=sup["identificacao"].apply(_num_amostra)).set_index("_num")
            loc = [numeros.loc[_num_amostra(i)] if _num_amostra(i) in numeros.index else None
                   for i in sub["identificacao"]]
            for c2 in ("ponto", "lon", "lat", "x", "y"):
                sub[c2] = [(r[c2] if isinstance(r, pd.Series) else np.nan) for r in loc]
        for a in av:
            avisos.append(f"{nome}: {a}")
        talhoes.append(Talhao(chave, nome, per_ll, per, sup, sub, av))

    sobras = set(perims) - set(ordem_laudo)
    if sobras:
        avisos.append(f"KML(s) de talhão sem amostras no laudo: {', '.join(sorted(sobras))}")
    return Projeto(epsg, talhoes, avisos)
