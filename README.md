# Recomendação de calcário, gesso, P2O5 e KCl a partir de laudos de solo

Plataforma simples: o usuário **anexa o laudo em Excel** e baixa um **Excel com as recomendações** por amostra.

```
laudo.xlsx ──► leitor (acha colunas e unidades) ──► motor determinístico (regras) ──► Excel de saída
                                    ▲                          ▲
                              interface Streamlit ── ajustes do calcário (CaO, MgO, PRNT) e limites
```

## Estrutura

| Arquivo | O que faz |
|---|---|
| `app.py` | Interface Streamlit (upload, marcar talhões de abertura, baixar Excel) |
| `motor/parametros.py` | **Todos os coeficientes e limites** num só lugar. Editar aqui muda o padrão |
| `motor/regras.py` | As quatro regras, em funções puras e testadas |
| `motor/leitor.py` | Lê o laudo: acha a linha de títulos, reconhece colunas por nome, lê a linha de unidades e converte |
| `motor/processar.py` | Aplica as regras a todas as amostras |
| `motor/saida.py` | Monta o Excel de recomendações |
| `motor/interpretacao.py` | Classes de teores (8 classes), médias por talhão e gráficos |
| `motor/saida_interpretacao.py` | Monta o Excel de interpretação (extra) |
| `assets/` | Logos, ícones e banner; `assets/book/` fotos das capas e seta de norte; `assets/fontes/` Montserrat (licença OFL) |
| `motor/geo.py` | Lê KML/KMZ, identifica o talhão pelo nome do arquivo e liga os pontos às amostras do laudo |
| `motor/krigagem.py` | Krigagem ordinária com semivariograma automático e tratamento de pontos atípicos |
| `motor/prescricao.py` | Superfícies por atributo, doses por pixel, zonas de manejo e shapefiles |
| `motor/externos.py` | Satélite, altitude (SRTM) e clima (NASA POWER) — consultados na hora, com internet |
| `motor/ndvi.py` | NDVI Sentinel-2 dos últimos 12 meses (pico de vigor e série por talhão) |
| `motor/juntar.py` | Reconhece e junta laudos (arquivos) da mesma fazenda |
| `motor/textura.py` | Reconhece dados ausentes no laudo e estima a argila pela CTC |
| `motor/ilustracoes.py` | Ilustrações autorais das capas (geral, fertilidade e prescrição), desenhadas em código |
| `motor/book.py` | Monta o book em PDF (A4) para Atria, Protecplan ou Ativa |
| `tests/` | Testes (`pytest`): regras conferidas à mão, mapas/shapefiles e funções da versão 7 |
| `exemplos/laudo_exemplo.xlsx` | Laudo fictício para testar |

## Regras implementadas

Unidades padrão: Ca, Mg, K, H+Al e Al em mmolc/dm³ · P e S em mg/dm³ · argila em g/kg.

**Calcário**
- CTC\* = Ca + Mg + H+Al + 5,6
- Dose = máx{ 85·(0,55·CTC\* − Ca) + 165·Al ; 345·(0,194·CTC\* − Mg) + 165·Al }
- Limites de 400 a 3.800 kg/ha. Em área de abertura, a dose já limitada é multiplicada por 1,8 (faixa de 720 a 6.840). A ordem pode ser invertida na interface.
- Correção quando o calcário não é o de referência (33% CaO, 14,9% MgO, PRNT 82):
  - critério Ca × (33 / CaO) × (82 / PRNT)
  - critério Mg × (14,9 / MgO) × (82 / PRNT)
  - termo do Al × (82 / PRNT)

**Gesso**
- Dose = ((S alvo − S) × 1000/75) × argila / 100
- S alvo: 35 mg/dm³ com argila < 200 g/kg; 25 com argila de 200 a 400; 20 com argila > 400
- Mínimo de 300 kg/ha (aplicado também quando o S já está acima do alvo, com aviso). Máximo de 1.800 kg/ha, com aviso.

**P2O5**
- 141,84 × P^−0,218, limitado a 55–105 kg/ha

**KCl (60% K2O)**
- 164,66 × K^−0,269 (K em mmolc/dm³), com mínimo de 100 kg/ha

**Camada 20-40 cm**: amostras cuja profundidade começa em 20 cm ou mais aparecem em vermelho na tela, mas não entram no cálculo nem na planilha de saída. Elas aparecem só na interpretação, como camada informativa.

**Ajustes de dose** (na tela, por laudo), aplicados à coluna inteira mantendo as proporções entre amostras:
- **Ajuste (%)**: aumenta ou reduz todas as doses.
- **Cliente já comprou**: informe a média (kg/ha) que o volume comprado permite; a coluna é escalada para chegar a essa média. Tem prioridade sobre o ajuste percentual.
- **Gesso → S elementar**: S elementar = 4,1904 × Gesso^0,3754.
- **Parcelamento do KCl**: divide a dose final de KCl em 2 aplicações (ex.: 60% + 40%). A 1ª parcela é arredondada e a 2ª recebe o restante, então as duas somam exatamente a dose total.
- **Formulação de P** (ex.: 11-52-00): cria a coluna do produto = P2O5 ÷ (%P2O5/100), além do N e K2O que o produto fornece (na memória de cálculo).

Arredondamento: calcário e gesso para múltiplos de 10 kg/ha, KCl de 5, P2O5 de 1 (pode ser alterado em `parametros.py`).

## Abas do app

- **🧪 Recomendação e book** — o fluxo completo (laudos → recomendações, interpretação, mapas, shapefiles e book).
- **📈 Comparações**, **🛰️ Satélites** e **🌱 Mapa de Sementes** — em desenvolvimento.

Granulometria: argila, areia e silte são lidas em g/kg (usadas assim nas contas do gesso) e **exibidas em %**
(÷ 10) nos mapas do book e na interpretação.

## Laudos sem granulometria ou sem micronutrientes

O leitor identifica os atributos que não vieram no laudo (sem coluna ou coluna vazia) e mostra um aviso 🔎.

- **Argila ausente** (usada só no gesso): estimada pela CTC a pH 7 com a equação ajustada em 2.085 amostras da
  base da equipe: **Argila (g/kg) = −186 + 6,57 × CTC (mmolc/dm³)** (R² = 0,78; erro típico ≈ 100 g/kg; a classe
  de argila do gesso é acertada em ~75% dos casos), limitada a 60–750 g/kg. Se a CTC não vier, usa-se
  Ca + Mg + H+Al + K. Se o laudo tiver argila em parte das amostras, a relação é recalibrada com elas
  (regressão local, ou correção do viés da equação regional). Cada valor estimado fica marcado na planilha
  (coluna *Argila - origem* e observação), na interpretação (textura "(est.)") e no book (metodologia; o mapa
  de argila sai do book quando a maioria das amostras é estimada).
- **Micronutrientes, areia ou silte ausentes:** ficam fora da interpretação e do book, sem erro.

## Blocos de aplicação (unir talhões na prescrição)

Na aba do book, em **🧩 Unir talhões na prescrição**, escreva o mesmo nome de bloco (ex.: *Bloco A*, *Pivô 1*)
nos talhões que devem sair juntos — ou marque *Todos os talhões num bloco só*. Os talhões de um bloco
recebem **as mesmas doses de zona** (calculadas com a faixa de doses do bloco inteiro) e saem num **shapefile
único por produto** (um registro por dose). No book, a prescrição do bloco mostra todos os talhões dele numa
página. Mapas de fertilidade e volumes por talhão não mudam.

## Vários laudos da mesma fazenda

Anexe todos os arquivos de uma vez. O app compara produtor e propriedade (ignorando acentos, "Fazenda/Faz.",
maiúsculas etc.) e sugere quais arquivos são da mesma fazenda (quadro 🔗). Arquivos com o mesmo número de grupo
viram **um laudo só**: uma planilha, uma interpretação e um book com todos os talhões. Dá para mudar o grupo
à mão. Na planilha, a coluna *Arquivo* mostra a origem de cada amostra e cada arquivo tem sua aba de laudo
original. Talhões com o mesmo nome em arquivos diferentes ganham a letra do arquivo (`1 (B)`). No book, se os
talhões de um arquivo estiverem a mais de 5 km dos demais, o app avisa.

## O Excel de saída

1. **Recomendações** – uma linha por amostra, com as 4 doses e observações
2. **Resumo por talhão** – média, mínimo e máximo de cada dose
3. **Memória de cálculo** – valores usados, resultado bruto de cada equação e o critério que definiu a dose
4. **Parâmetros** – calcário, coeficientes e limites usados, colunas lidas e avisos (garante rastreabilidade)
5. **Laudo original** – cópia do que foi enviado (somente as linhas de 0-20 cm)

## O Excel de interpretação (extra)

Situação média de cada talhão classificada nas 8 classes da tabela de legendas da equipe (Crítico → Muito alto), com as mesmas cores:
1. **Diagnóstico 0-20 cm** – médias coloridas por classe e pontos de atenção por talhão
2. **Camada 20-40 cm** – o mesmo para a camada subsuperficial, se houver
3. **Gráficos** – mapa de classes e doses médias por talhão
4. **Classes (lista)** – formato longo, para filtrar
5. **Faixas de referência** – os limites de cada classe (editáveis em `motor/interpretacao.py`)

## Book de fertilidade e prescrições (aba "📚 Montar book")

1. Anexe o laudo e ajuste as recomendações normalmente (abertura, ajustes, parcelamento etc.).
2. Na aba **Montar book**, anexe os KML/KMZ de **perímetro** e de **pontos** de cada talhão.
   O talhão é lido do nome do arquivo (`Perimetro_TH_1.kml`, `Pontos_TH_2.kmz`…) e pode ser corrigido na tabela.
3. Ligação laudo ↔ pontos: dentro de cada talhão, as amostras de 0-20 cm, na ordem do laudo, correspondem
   aos pontos 1, 2, 3… do KML. Amostras de 20-40 cm herdam o ponto da amostra de mesmo número.
4. Escolha a marca (Atria, Protecplan ou Ativa), preencha município e data da coleta e clique em **Gerar**.

Saídas: **book em PDF** e **.zip com os shapefiles** de prescrição (uma pasta por talhão; WGS84; campo
`Taxa_Dest_`, como o padrão usado hoje; com arquivo .prj). Depois de gerar, escolha **quais produtos** entram
no .zip.

**Fósforo:** informe no formulário do book a **formulação comprada** (ex.: 11-52-00) — vem preenchida com a
da aba de ajustes. O mapa e o shapefile saem em dose do produto. Sem formulação, o mapa mostra P₂O₅
(nutriente, um "00-100-00" que não existe) e o shapefile de P₂O₅ fica bloqueado (pode ser liberado só para
conversão manual). **KCl parcelado:** também definido no formulário; o book traz um mapa por aplicação.

Como os mapas são feitos:
- Todos os atributos são interpolados numa grade de 10 m por **krigagem ordinária** (padronizado para todos
  os talhões e atributos). O semivariograma é ajustado automaticamente (esférico, exponencial ou gaussiano,
  por validação cruzada); quando a malha amostral não detecta a estrutura espacial (alcance menor que a
  distância entre pontos ou efeito pepita puro), usa-se um semivariograma padrão (esférico, pepita 15%,
  alcance de 2,5× a distância entre pontos). Os detalhes de cada mapa ficam no app, em
  "Detalhes da krigagem" (uso interno).
- **Pontos atípicos:** valores além de 3 intervalos interquartis são limitados; e um ponto muito diferente dos
  6 vizinhos (resíduo > 3 desvios robustos) é trazido para a faixa dos vizinhos. Isso evita os "alvos"
  (círculos concêntricos de dose) que um único ponto cria. O valor do laudo e a dose da planilha não mudam.
- As doses são calculadas **em cada pixel pelas mesmas regras da planilha** (e com os mesmos ajustes);
  depois são agrupadas em até 6 zonas com **largura mínima de 30 m** e **área mínima de 0,5 ha**.
- As cores dos mapas de fertilidade seguem as 8 classes da tabela de legendas da equipe (faixas sólidas, 1 cor por classe;
  há opção de transição suave); a legenda traz a área de cada classe e a média de cada talhão, com unidade.
- Fazendas com muitos talhões: talhões próximos (< 2,5 km) ficam na mesma página; grupos distantes ganham páginas próprias.

Dados externos (precisam de internet no servidor; se falharem, o book sai sem aquela parte e avisa):
- Satélite: Google (Map Tiles API, precisa de `google_maps_key` nos Secrets), Esri World Imagery ou
  Sentinel-2 cloudless (EOX, CC BY 4.0). Se a fonte escolhida falhar, o app tenta a Esri. Tiles baixados em paralelo.
- Altitude: SRTM por tiles de terreno (Terrain Tiles, AWS Open Data) — poucas requisições, valor em cada pixel;
  reserva: OpenTopoData/Open-Meteo por pontos (no máximo ~800 pontos).
- Clima: normais mensais da NASA POWER.
- **NDVI** (opcional, marcado por padrão): Sentinel-2 L2A (Copernicus) via Earth Search, sem chave. Uma data por mês
  nos últimos 12 meses, nuvens removidas pela máscara SCL; página com o **pico de vigor** (NDVI máximo) em
  7 classes fixas, a **evolução do NDVI** e o pico médio/CV de cada talhão. Soma cerca de 20–40 s.

Capas (v10): artes da equipe em `assets/book/capa_geral.jpg`, `capa_fertilidade.jpg` e `capa_prescricao.jpg`
(página inteira; o título fica na área do céu e o produtor/propriedade num cartão na capa geral). Para trocar
uma arte, substitua o arquivo mantendo o nome (formato retrato, proporção próxima de A4, céu claro no topo) e,
se o céu ficar mais alto ou mais baixo, ajuste `CAPAS` em `motor/book.py`. Se o arquivo faltar, o book usa as
ilustrações desenhadas em código (`motor/ilustracoes.py`): ilustrações autorais (paisagem com talhões, pivô, amostragem georreferenciada, drone
e satélite na capa geral; perfil do solo, trado, troca de cátions, agregados e vidraria na capa de fertilidade;
talhão em zonas de dose, trator com distribuidor a lanço de taxa variável e GNSS na capa de prescrição), nas
cores de cada marca.

Desempenho: a leitura do laudo, as figuras da interpretação e os Excel são guardados em cache/gerados só no
clique; a validação cruzada da krigagem usa a fórmula fechada (uma inversão por modelo). Um book de 12 talhões
(~1.800 ha) leva ~25 s de processamento, mais o tempo das consultas externas.

## Rodar no computador

```bash
pip install -r requirements.txt
streamlit run app.py          # abre em http://localhost:8501
pytest                        # roda os testes
```

## Hospedagem gratuita (Streamlit Community Cloud)

1. Crie uma conta no GitHub e um repositório novo; envie esta pasta para ele (pode usar o botão *"Add file → Upload files"* no site).
2. Acesse **share.streamlit.io** e entre com a conta do GitHub.
3. Clique em **Create app**, escolha o repositório, branch `main` e arquivo `app.py`, e depois **Deploy**.
4. Em poucos minutos você recebe um endereço `https://<nome>.streamlit.app` para compartilhar com os colegas.
5. **Senha e música:** no painel do app, abra *Settings → Secrets* e cole (veja `.streamlit/secrets.toml.exemplo`):
   ```
   senha = "sua-senha"
   playlist = "https://www.youtube.com/playlist?list=..."
   ```
   A playlist pode ser do YouTube ou do Spotify. O botão 🎵 na barra lateral liga e desliga o player. No Spotify, só quem estiver logado ouve as faixas completas; no YouTube, todos ouvem.

Observações:
- Os laudos são processados em memória e **não ficam gravados** no servidor. O repositório tem apenas código e um laudo fictício; não suba laudos reais.
- Apps gratuitos "dormem" depois de alguns dias sem uso. O primeiro acesso depois disso leva cerca de 30 s para acordar.
- Alternativas gratuitas, se preferir: Hugging Face Spaces (modelo "Streamlit") ou Render.

## Como alterar regras

- **Garantias do calcário, limites e S alvo:** na barra lateral do app (vale só para aquela sessão).
- **Mudança permanente:** edite `motor/parametros.py`, rode `pytest` e envie ao GitHub. O app atualiza sozinho.
- **Colunas com outros nomes:** acrescente o nome em `ALIASES`, no `motor/leitor.py` (sem acento, minúsculo, sem espaços).
