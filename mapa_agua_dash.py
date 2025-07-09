# mapa_agua_dash.py
from pathlib import Path
import json
import pandas as pd
import plotly.express as px

from dash import Dash, dcc, html
from dash.dependencies import Input, Output

# 1) Rutas de archivos
base = Path(".")
file       = base / "base final.dta"
pop_file   = base / "Poblacion regiones Chile.dta"
aus_file   = base / "DAA Australia y pob.xlsx"
geo_file   = base / "regiones_rotated.json"

# 2) Carga el GeoJSON ya rotado
with open(geo_file, "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

# 3) Lee y procesa las transacciones de Chile
valid_types = [
    "ARRENDAMIENTO", "CESION", "COMPRAVENTA", "DACION EN PAGO",
    "DONACION", "LIQUIDACIÓN", "PERMUTA"
]
df = pd.read_stata(file)
df = df[df["TipodeTransacción"].isin(valid_types)]
df = df.rename(columns={
    "numero_region": "region_id",
    "RegistroAñoCBRActual": "year"
})
df["year"] = df["year"].astype(int)

counts = (
    df
    .groupby(["region_id", "year"])
    .size()
    .reset_index(name="n_ventas")
)

# 4) Población por región y año
pop = pd.read_stata(pop_file)
pop_long = pop.melt(
    id_vars="region", var_name="year", value_name="population"
)
pop_long["year"] = pop_long["year"].str.lstrip("a").astype(int)
num_to_roman = {
    1:"I",2:"II",3:"III",4:"IV",5:"V",6:"VI",7:"VII",8:"VIII",
    9:"IX",10:"X",11:"XI",12:"XII",13:"XIII",14:"XIV",15:"XV",16:"XVI"
}
pop_long["region_id"] = pop_long["region"].map(num_to_roman)

counts = counts.merge(
    pop_long[["region_id","year","population"]],
    on=["region_id","year"], how="left"
)
counts["ventas_per_capita"] = counts["n_ventas"] / counts["population"]
global_max_pc = counts["ventas_per_capita"].max()

# 5) Datos de Australia
aus = pd.read_excel(aus_file)
aus.columns = aus.columns.str.strip()
aus = aus.rename(columns={
    "Total trades":"n_ventas",
    "Población Australia":"population",
    "Transacciones per capita":"ventas_per_capita"
})
for col in ["year","n_ventas","population"]:
    aus[col] = aus[col].astype(int)
aus["ventas_per_capita"] = aus["ventas_per_capita"].astype(float)

# 6) Prepara slider
years = sorted(counts["year"].unique())

# 7) Crea la app Dash
app = Dash(__name__)
app.title = "Ventas per cápita Derechos de Agua Chile"

app.layout = html.Div(
    [
        html.H1("Transacciones de derechos de agua per cápita en Chile"),
        dcc.Slider(
            id="year-slider",
            min=years[0], max=years[-1],
            step=1, value=years[0],
            marks={y: str(y) for y in years},
            updatemode="drag"
        ),
        dcc.Graph(id="choropleth-map"),
        html.Div(id="total-chile", style={"fontSize": "18px", "marginTop": "10px"}),
        html.Div(
            "Nota: solo tipos " + ", ".join(valid_types),
            style={"fontSize": "10px", "fontStyle": "italic", "marginTop": "5px"}
        )
    ],
    style={"width": "80%", "margin": "auto"}
)

# 8) Callback
@app.callback(
    Output("choropleth-map", "figure"),
    Output("total-chile", "children"),
    Input("year-slider", "value")
)
def update_map(selected_year):
    df_year = counts[ counts["year"] == selected_year ].copy()
    abs_total = int(df_year["n_ventas"].sum())
    total_pop = df_year["population"].sum()
    percap_total = abs_total / total_pop if total_pop else 0

    # Texto Australia
    aus_row = aus[aus["year"] == selected_year]
    if not aus_row.empty:
        a = aus_row.iloc[0]
        aus_text = f" — Australia {selected_year}: {int(a.n_ventas)} ({a.ventas_per_capita:.4f} per cápita)"
    else:
        aus_text = ""

    total_text = f"Total Chile {selected_year}: {abs_total} ({percap_total:.4f} per cápita){aus_text}"

    # Mapa
    fig = px.choropleth(
        df_year,
        geojson=geojson_data,
        locations="region_id",
        featureidkey="properties.region_id",
        color="ventas_per_capita",
        range_color=(0, global_max_pc),
        hover_name="region_id",
        hover_data=["n_ventas", "population", "ventas_per_capita"],
        projection="mercator",
        labels={"ventas_per_capita": "ventas per cápita"}
    )
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(margin={"l":0,"r":0,"t":0,"b":0}, height=500)

    return fig, total_text

# 9) Ejecuta servidor
if __name__ == "__main__":
    app.run(debug=True)

