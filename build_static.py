# build_static.py
import json
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
import plotly.express as px

# --- 1) Rutas de archivos ---
base      = Path(".")
file      = base / "base final.dta"
pop_file  = base / "Poblacion regiones Chile.dta"
aus_file  = base / "DAA Australia y pob.xlsx"
geo_file  = base / "regiones.json"

# --- 2) Pre-procesa geometrías de Chile ---
gdf = gpd.read_file(geo_file)
gdf["geometry"] = gdf.geometry.buffer(0)  # limpia invalid geometries

# Rotación 90° alrededor del centroide
union   = unary_union(gdf.geometry)
centrod = union.centroid
gdf["geometry"] = gdf.geometry.rotate(90, origin=(centrod.x, centrod.y))

# Mapea codregion → region_id (romanos)
gdf = gdf.rename(columns={"codregion":"region_num"})
gdf["region_num"] = gdf["region_num"].astype(int)
num_to_roman = {
    1:"I",2:"II",3:"III",4:"IV",5:"V",6:"VI",7:"VII",8:"VIII",
    9:"IX",10:"X",11:"XI",12:"XII",13:"XIII",14:"XIV",15:"XV",16:"XVI"
}
gdf["region_id"] = gdf["region_num"].map(num_to_roman)

# Crea el geojson que usará Plotly
geojson = json.loads(gdf[["region_id","geometry"]].to_json())

# Calcula bounds globales para centrar la proyección
minx, miny, maxx, maxy = gdf.total_bounds
lat_pad = (maxy - miny) * 0.05
mid_lat = (miny + maxy) / 2.9
mid_lon = (minx + maxx) / 2

# --- 3) Carga y procesa datos de Chile ---
valid_types = [
    "ARRENDAMIENTO","CESION","COMPRAVENTA","DACION EN PAGO",
    "DONACION","LIQUIDACIÓN","PERMUTA"
]
df = pd.read_stata(file)
df = df[df["TipodeTransacción"].isin(valid_types)]
df = df.rename(columns={
    "numero_region":"region_id",
    "RegistroAñoCBRActual":"year"
})
df["year"] = df["year"].astype(int)
counts = df.groupby(["region_id","year"]).size().reset_index(name="n_ventas")

pop = (
    pd.read_stata(pop_file)
      .melt(id_vars="region", var_name="year", value_name="population")
)
pop["year"] = pop["year"].str.lstrip("a").astype(int)
pop["region_id"] = pop["region"].map(num_to_roman)

counts = counts.merge(
    pop[["region_id","year","population"]],
    on=["region_id","year"], how="left"
)
counts["ventas_per_100k"] = counts["n_ventas"] / counts["population"] * 100000
global_max_100k = counts["ventas_per_100k"].max()

# --- 4) Carga datos de Australia ---
aus = pd.read_excel(aus_file)
aus.columns = aus.columns.str.strip()
aus = aus.rename(columns={
    "Total trades":"n_ventas",
    "Población Australia":"population",
    "Transacciones per capita":"ventas_per_capita"
})
aus["year"] = aus["year"].astype(int)
aus["ventas_per_capita"] = aus["ventas_per_capita"].astype(float)

# --- 5) Prepara texto dinámico para totales ---
year_text = {}
for yr in sorted(counts["year"].unique()):
    cy = counts[counts["year"]==yr]
    abs_chile = int(cy["n_ventas"].sum())
    pop_chile = cy["population"].sum()
    per100k   = abs_chile / pop_chile * 100000 if pop_chile else 0

    ay = aus[aus["year"]==yr]
    if not ay.empty:
        a0 = ay.iloc[0]
        aus100k = a0.n_ventas / a0.population * 100000
        txt_aus  = f" — Australia {yr}: {int(a0.n_ventas)} ({aus100k:.1f} por 100 000 pers.)"
    else:
        txt_aus = ""

    year_text[str(yr)] = (
        f"Total Chile {yr}: {abs_chile} compraventas "
        f"({per100k:.1f} por 100 000 pers.){txt_aus}"
    )
# --- antes, calcula `years` y `year_text` tal como lo tenías ---
# --- 5.1) Define la lista ordenada de años para el slider ---
years = sorted(counts["year"].unique())

# 6) Construye la figura con slider por año Y ORDÉNALA BIEN
fig = px.choropleth(
    counts,
    geojson=geojson,
    locations="region_id",
    featureidkey="properties.region_id",
    color="ventas_per_100k",
    range_color=(0, global_max_100k),
    hover_name="region_id",
    hover_data={
        "ventas_per_100k": True,
        "n_ventas": True,
        "population": True
    },
    projection="mercator",
    color_continuous_scale="Viridis",
    labels={"ventas_per_100k":"ventas per cápita"},
    animation_frame="year",
    # <— fuerza el orden correcto
    category_orders={"year": years}
)

# 7) Aplica TU mismo estilo de geos y tamaño exacto
fig.update_geos(
    visible=False,
    projection_type="mercator",
    lataxis_range=[miny - lat_pad, maxy + lat_pad],
    center={"lon": mid_lon, "lat": mid_lat},
    projection_scale=8,
)
# aumentamos bottom margin para pie y texto
fig.update_layout(
    width=1300,
    height=500,
    margin={"l":0,"r":0,"t":0,"b":100}
)

# 8) Añade la FOOTNOTE fija bajo el mapa
foot = (
    "Nota: para Chile se consideran sólo transacciones de tipo "
    + ", ".join(valid_types) + "."
)
fig.add_annotation(
    x=0, y=-0.08, xref="paper", yref="paper",
    text=foot, showarrow=False,
    font=dict(size=10, style="italic"), align="left"
)

# 9) Añade el TEXTO DINÁMICO de cada año justo encima de la footnote
for frm in fig.frames:
    txt = year_text.get(str(frm.name), "")
    # borra cualquier otra anotación de ese frame y pon la tuya:
    frm.layout.annotations = [
        dict(
            x=0, y=-0.04, xref="paper", yref="paper",
            text=txt, showarrow=False,
            font=dict(size=14), align="left"
        )
    ]

# 10) Exporta tu HTML
fig.write_html(
    "index.html",
    include_plotlyjs="cdn",
    full_html=True
)
print("✅ index.html generado con slider ordenado y footnote visible")
