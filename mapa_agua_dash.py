# mapa_agua_dash.py
from pathlib import Path
import pandas as pd
import geopandas as gpd
import plotly.express as px
from shapely.ops import unary_union

from dash import Dash, dcc, html
from dash.dependencies import Input, Output

# 1) Carga y prepara los datos
base = Path(".")
file = base / "base final.dta"
pop_file = base / "Poblacion regiones Chile.dta"
aus_file = base / "DAA Australia y pob.xlsx"
geo_file = base / "regiones.json"

# Leer y filtrar sólo los tipos de transacción relevantes
valid_types = [
    "ARRENDAMIENTO", "CESION", "COMPRAVENTA", "DACION EN PAGO",
    "DONACION", "LIQUIDACIÓN", "PERMUTA"
]
df = pd.read_stata(file)
df = df[df["TipodeTransacción"].isin(valid_types)]

# Renombrar columnas y convertir año
df = df.rename(columns={
    "numero_region": "region_id",
    "RegistroAñoCBRActual": "year"
})
df["year"] = df["year"].astype(int)

# Contar ventas por región-año
counts = (
    df
    .groupby(["region_id", "year"])
    .size()
    .reset_index(name="n_ventas")
)

# 2) Carga y prepara la población
pop = pd.read_stata(pop_file)
pop_long = pop.melt(
    id_vars='region', var_name='year', value_name='population'
)
pop_long['year'] = pop_long['year'].str.lstrip('a').astype(int)
num_to_roman = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI",
    7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI",
    12: "XII", 13: "XIII", 14: "XIV", 15: "XV", 16: "XVI"
}
pop_long['region_id'] = pop_long['region'].map(num_to_roman)

# Une population con counts y calcula per cápita
counts = counts.merge(
    pop_long[['region_id', 'year', 'population']],
    on=['region_id', 'year'], how='left'
)
counts['ventas_per_capita'] = counts['n_ventas'] / counts['population']
global_max_pc = counts['ventas_per_capita'].max()

global_max = counts['n_ventas'].max()

# 3) Carga y prepara datos de Australia
aus = pd.read_excel(aus_file)
# Normalizar nombres de columna
aus.columns = aus.columns.str.strip()
# Renombrar según lo que contiene tu Excel
aus = aus.rename(columns={
    'Total trades': 'n_ventas',
    'Población Australia': 'population',
    'Transacciones per capita': 'ventas_per_capita'
})
# Asegurar tipos correctos
aus['year'] = aus['year'].astype(int)
aus['n_ventas'] = aus['n_ventas'].astype(int)
aus['population'] = aus['population'].astype(int)
aus['ventas_per_capita'] = aus['ventas_per_capita'].astype(float)

# 3) Carga y prepara la geometría
regions = gpd.read_file(geo_file)
regions['geometry'] = regions['geometry'].buffer(0)
regions = regions.rename(columns={'codregion': 'region_num'})
regions['region_num'] = regions['region_num'].astype(int)
regions['region_id'] = regions['region_num'].map(num_to_roman)

chile_union    = unary_union(regions.geometry)
chile_centroid = chile_union.centroid

# 4) Construir el DataFrame completo región–año con geometría
years = sorted(counts["year"].unique())
region_ids = sorted(regions["region_id"].unique())
full = pd.MultiIndex.from_product([
    region_ids, years], names=["region_id", "year"]
)
df_map = (
    counts
    .set_index(["region_id", "year"])
    .reindex(full, fill_value=0)
    .reset_index()
    .merge(regions[["region_id", "geometry"]], on="region_id", how="left")
)

gdf_map = gpd.GeoDataFrame(df_map, geometry="geometry")

# 5) Inicializa la app Dash
app = Dash(__name__)
app.title = "Ventas per cápita Derechos de Agua Chile"

app.layout = html.Div([
    html.H1("Transacciones de derechos de agua per cápita en Chile"),
    dcc.Slider(
        id="year-slider",
        min=int(years[0]), max=int(years[-1]), step=1,
        value=int(years[0]), marks={int(y): str(y) for y in years},
        updatemode="drag"
    ),
    dcc.Graph(id="choropleth-map"),
    html.Div(id="total-chile", style={"fontSize": "18px", "marginTop": "10px"}),
    html.Div(
        "Nota: para Chile se consideran sólo transacciones de tipo " + ", ".join(valid_types) + ".",
        style={"fontSize": "10px", "fontStyle": "italic", "marginTop": "5px"}
    )
], style={"width": "80%", "margin": "auto"})

# 6) Callback para actualizar mapa y total
@app.callback(
    Output("choropleth-map", "figure"),
    Output("total-chile", "children"),
    Input("year-slider", "value")
)
def update_map(selected_year):
    df_year = gdf_map[gdf_map["year"] == selected_year].copy()

    abs_total = int(df_year['n_ventas'].sum())
    total_population = df_year['population'].sum()
    percap_total = abs_total / total_population if total_population else 0

    df_year['geometry'] = df_year.geometry.rotate(
        90, origin=(chile_centroid.x, chile_centroid.y)
    )

    df_year["location_id"] = df_year.index.astype(str)
    geojson = df_year.__geo_interface__

    fig = px.choropleth(
        df_year, geojson=geojson, locations="location_id",
        color="ventas_per_capita", range_color=(0, global_max_pc),
        hover_name="region_id", hover_data={
            "ventas_per_capita": True,
            "n_ventas": True,
            "population": True
        }, projection="mercator",
        color_continuous_scale="Viridis",
        labels={"ventas_per_capita": "ventas per cápita"}
    )

    minx, miny, maxx, maxy = df_year.total_bounds
    lat_pad = (maxy - miny) * 0.05
    mid_lat = (miny + maxy) / 2.9
    mid_lon = (minx + maxx) / 2
    fig.update_geos(
        visible=False,
        projection_type="mercator",
        lataxis_range=[miny - lat_pad, maxy + lat_pad],
        center={"lon": mid_lon, "lat": mid_lat},
        projection_scale=8,
    )

    fig.update_layout(
        width=1300, height=500,
        margin={"l": 0, "r": 0, "t": 0, "b": 0}
    )

    # extracción de totales de Australia para el año seleccionado
    aus_rows = aus[aus['year'] == selected_year]
    if not aus_rows.empty:
        aus_abs = int(aus_rows.iloc[0]['n_ventas'])
        aus_pc = aus_rows.iloc[0]['ventas_per_capita']
        australia_text = (
            f" — Australia {selected_year}: {aus_abs} compraventas "
            f"({aus_pc:.4f} per cápita)"
        )
    else:
        australia_text = ""

    # texto del total incluyendo Chile y Australia (si hay datos)
    total_text = (
        f"Total Chile {selected_year}: {abs_total} compraventas "
        f"({percap_total:.4f} per cápita)"
        f"{australia_text}"
    )
    return fig, total_text


# 7) Ejecuta el servidor
if __name__ == "__main__":
    app.run(debug=True)
if __name__ == "__main__":
    app.run(debug=True)
