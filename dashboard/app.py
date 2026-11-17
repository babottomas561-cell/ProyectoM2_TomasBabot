"""
FleetLogix - Tablero de operación (Streamlit)

Usa datos reales del Data Warehouse en Snowflake (FLEETLOGIX_DW.ANALYTICS), exportados con
2. Scripts/07_export_dashboard_data.py a dashboard/data/. Así se puede abrir sin conectarse a Snowflake.

Para abrirlo (desde la carpeta del proyecto):  streamlit run dashboard/app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='FleetLogix · Tablero', page_icon='🚚', layout='wide')

CARPETA = Path(__file__).parent
DATOS = CARPETA / 'data'

# Colores (los mismos tonos que mi tablero de ventas retail)
AZUL, AZUL_SUAVE, GRIS = '#2563EB', 'rgba(37, 99, 235, 0.08)', '#9CA3AF'
TEXTO_2 = '#6B7280'
COLORES_VEHICULO = {'Camión Grande': '#2a78d6', 'Camión Mediano': '#eb6834', 'Van': '#1baf7a', 'Motocicleta': '#eda100'}
COLORES_CATEGORIA = {'Alto': '#2a78d6', 'Medio': '#eb6834', 'Bajo': '#1baf7a'}
MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
TURNOS = {'Turno 1': 'Turno 1 · 06 a 14 h', 'Turno 2': 'Turno 2 · 14 a 22 h', 'Turno 3': 'Turno 3 · 22 a 06 h'}
COORDENADAS = {'Bogotá': (4.711, -74.072), 'Medellín': (6.244, -75.581), 'Cali': (3.452, -76.532),
               'Barranquilla': (10.969, -74.781), 'Cartagena': (10.391, -75.479)}

st.markdown("""
<style>
  /* Tarjetas blancas con sombra suave, como en el tablero retail */
  [class*="st-key-tarjeta-"], [data-testid="stMetric"] {
      background: #FFFFFF; box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.08); }
  .tarjeta-titulo { font-weight: 600; font-size: 0.98rem; color: #111827; margin-bottom: 0.1rem; }
  .tarjeta-titulo span { font-weight: 400; font-size: 0.85rem; color: #6B7280; margin-left: 0.4rem; }
  .lectura { background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 12px; padding: 0.75rem 1rem;
             color: #78350F; font-size: 0.92rem; margin-bottom: 0.5rem; }
  .nota { color: #6B7280; font-size: 0.82rem; }
  [data-testid="stMetricValue"] { font-size: 1.55rem; font-weight: 600; }
  [data-testid="stSidebar"] .pie { color: #94A3B8; font-size: 0.78rem; }
  .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)


# ================================================================ Datos
@st.cache_data
def cargar_datos():
    entregas = pd.read_parquet(DATOS / 'entregas_diarias.parquet')
    # Saco los días incompletos de los bordes: el primero y los últimos tienen viajes que todavía no terminaron
    # (por ejemplo 23 entregas el último día contra ~550 de un día normal) y bajarían los totales y las comparaciones.
    por_dia = entregas.groupby('fecha')['entregas'].sum()
    completos = por_dia[por_dia >= 0.8 * por_dia.median()].index
    dias_excluidos = por_dia[(por_dia.index < completos.min()) | (por_dia.index > completos.max())]
    entregas = entregas[entregas['fecha'].between(completos.min(), completos.max())].copy()
    entregas['anio'] = entregas['fecha'].dt.year
    entregas['mes'] = entregas['fecha'].dt.to_period('M').dt.to_timestamp()
    entregas['dia'] = pd.Categorical(entregas['fecha'].dt.dayofweek.map(dict(enumerate(DIAS))), DIAS, ordered=True)
    entregas['turno'] = entregas['turno'].map(TURNOS)
    conductores = pd.read_parquet(DATOS / 'conductores.parquet')
    return entregas, conductores, dias_excluidos


def resumen(df, por=None):
    """Suma las métricas y calcula los porcentajes. Sin 'por' devuelve una sola fila con el total."""
    columnas = ['entregas', 'entregas_a_tiempo', 'peso_kg', 'km', 'litros', 'ingreso', 'costo', 'minutos_entrega']
    g = df[columnas].sum().to_frame().T if por is None else df.groupby(por, observed=True)[columnas].sum().reset_index()
    g['pct_a_tiempo'] = 100 * g['entregas_a_tiempo'] / g['entregas']
    g['margen_pct'] = 100 * (g['ingreso'] - g['costo']) / g['ingreso']
    g['minutos_promedio'] = g['minutos_entrega'] / g['entregas']
    g['litros_100km'] = 100 * g['litros'] / g['km']
    return g


def numero(x, decimales=0):
    """Formato argentino: 1.234.567,8"""
    return f'{x:,.{decimales}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ================================================================ Piezas visuales
def tarjeta(titulo, subtitulo=''):
    """Contenedor blanco con título y subtítulo gris (cada gráfico va en una tarjeta)."""
    clave = 'tarjeta-' + ''.join(c if c.isalnum() else '-' for c in titulo.lower())
    caja = st.container(border=True, key=clave)
    caja.markdown(f'<div class="tarjeta-titulo">{titulo}<span>{subtitulo}</span></div>', unsafe_allow_html=True)
    return caja


def lectura(texto):
    st.markdown(f'<div class="lectura"><b>Lectura:</b> {texto}</div>', unsafe_allow_html=True)


def estilo(fig, alto=320, leyenda=False):
    """Estilo común de los gráficos: fondo blanco, grilla suave, sin título (el título va en la tarjeta)."""
    fig.update_layout(
        template='plotly_white', height=alto, margin=dict(l=10, r=10, t=10, b=10),
        font=dict(family='Inter, sans-serif', size=12, color='#374151'),
        showlegend=leyenda, legend=dict(orientation='h', y=1.08, x=0, title_text=''),
        hoverlabel=dict(bgcolor='white', font_size=12), coloraxis_showscale=False,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', bargap=0.35,
        separators=',.')  # coma decimal y punto de miles, como en el resto del tablero
    fig.update_xaxes(showgrid=False, linecolor='#E5E7EB', title_text='')
    fig.update_yaxes(gridcolor='#EEF1F6', zeroline=False, title_text='')
    return fig


def mostrar(caja, fig, datos=None, nombre=None):
    """Muestra el gráfico en la tarjeta. Si le paso 'datos', agrega una pestaña con la tabla y un botón para
    bajarla en CSV (la idea de chart_container de streamlit-extras, pero con los textos en español)."""
    config = {'displayModeBar': False}
    if datos is None:
        caja.plotly_chart(fig, width='stretch', config=config)
        return
    grafico, tabla = caja.tabs([':material/bar_chart: Gráfico', ':material/table: Datos'])
    grafico.plotly_chart(fig, width='stretch', config=config)
    tabla.dataframe(datos, hide_index=True, width='stretch')
    # Separador ';' y coma decimal para que Excel en español lo abra bien en columnas
    csv = datos.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
    tabla.download_button('Descargar CSV', csv, file_name=f'fleetlogix_{nombre}.csv', mime='text/csv',
                          icon=':material/download:', key=f'descarga-{nombre}')


def para_descargar(df, columnas):
    """Elige y renombra las columnas que se ven en la pestaña Datos. columnas = {columna: título}."""
    return df[list(columnas)].rename(columns=columnas).round(2)


def barras_horizontales(datos, x, y, formato, color=AZUL, colores=None):
    fig = px.bar(datos, x=x, y=y, orientation='h', text=datos[x].map(formato),
                 color=y if colores else None, color_discrete_map=colores)
    if not colores:
        fig.update_traces(marker_color=color)
    fig.update_traces(cliponaxis=False, marker_cornerradius=4, hovertemplate='%{y}: %{text}<extra></extra>')
    # Positivos: etiqueta afuera, a la derecha. Negativos: adentro de la barra en blanco,
    # porque afuera quedaría encima del nombre de la categoría.
    for traza in fig.data:
        negativos = [v < 0 for v in traza.x]
        traza.textposition = ['inside' if n else 'outside' for n in negativos]
        traza.insidetextanchor = 'middle'
        traza.insidetextfont = dict(color='white')
    minimo, maximo = min(datos[x].min(), 0), max(datos[x].max(), 0)
    fig.update_xaxes(range=[minimo, maximo + 0.18 * (maximo - minimo)])  # lugar a la derecha para las etiquetas
    return estilo(fig, alto=70 + 44 * len(datos))


# ================================================================ Filtros (en la barra lateral, valen para todas las páginas)
entregas, conductores, dias_excluidos = cargar_datos()
fecha_min, fecha_max = entregas['fecha'].min(), entregas['fecha'].max()

st.logo(str(CARPETA / 'logo.svg'), size='large')

with st.sidebar:
    st.divider()
    periodo = st.selectbox('Período', ['2026 (en curso)', '2025', 'Todo (2 años)', 'Elegir fechas'])
    if periodo == 'Elegir fechas':
        rango = st.date_input('Desde / hasta', value=(fecha_max - pd.DateOffset(months=3), fecha_max),
                              min_value=fecha_min, max_value=fecha_max, format='DD/MM/YYYY')
        # Mientras el usuario elige, date_input devuelve una sola fecha: hasta que elija la segunda uso esa sola
        desde, hasta = (rango[0], rango[-1]) if rango else (fecha_min, fecha_max)
    else:
        desde, hasta = {'2026 (en curso)': ('2026-01-01', fecha_max), '2025': ('2025-01-01', '2025-12-31'),
                        'Todo (2 años)': (fecha_min, fecha_max)}[periodo]
    desde, hasta = pd.Timestamp(desde), pd.Timestamp(hasta)
    ciudades = st.multiselect('Ciudad de destino', list(COORDENADAS), placeholder='Todas')
    vehiculos = st.multiselect('Tipo de vehículo', list(COLORES_VEHICULO), placeholder='Todos')
    turnos = st.multiselect('Turno', list(TURNOS.values()), placeholder='Todos')
    st.divider()
    excluidos = ', '.join(f'{d:%d/%m/%Y}' for d in dias_excluidos.index)
    st.markdown(f'<div class="pie">● Data Warehouse en Snowflake<br>Datos del {fecha_min:%d/%m/%Y} al {fecha_max:%d/%m/%Y}<br>'
                f'Sin los días incompletos: {excluidos}<br>'
                f'{numero(len(entregas))} filas resumidas de fact_deliveries</div>', unsafe_allow_html=True)


def aplicar_filtros(df, con_periodo=True):
    if ciudades:
        df = df[df['ciudad'].isin(ciudades)]
    if vehiculos:
        df = df[df['tipo_vehiculo'].isin(vehiculos)]
    if turnos:
        df = df[df['turno'].isin(turnos)]
    if con_periodo:
        df = df[df['fecha'].between(desde, hasta)]
    return df


def encabezado(titulo, df):
    st.title(titulo)
    if df.empty:
        st.warning('No hay entregas con esta combinación de filtros.')
        st.stop()
    st.markdown(f'<div class="nota">{numero(df["entregas"].sum())} entregas completadas · '
                f'{df["fecha"].min():%d/%m/%Y} al {df["fecha"].max():%d/%m/%Y}</div>', unsafe_allow_html=True)
    st.write('')


# ================================================================ Página: Resumen
def pagina_resumen():
    base = aplicar_filtros(entregas, con_periodo=False)
    df = aplicar_filtros(entregas)
    encabezado('Resumen de la operación', df)

    # Indicadores. Los comparo con el mismo período un año antes, si hay datos de esas fechas.
    actual = resumen(df).iloc[0]
    previo = None
    desde_previo, hasta_previo = desde - pd.DateOffset(years=1), hasta - pd.DateOffset(years=1)
    if desde_previo >= fecha_min:
        mismo_periodo = base[base['fecha'].between(desde_previo, hasta_previo)]
        previo = resumen(mismo_periodo).iloc[0] if not mismo_periodo.empty else None

    def delta(col, en_puntos=False):
        if previo is None:
            return None
        if en_puntos:
            return f'{numero(actual[col] - previo[col], 1)} pp'
        return f'{numero(100 * (actual[col] / previo[col] - 1), 1)} %'

    # Minigráfico de cada indicador: por mes, semana o día según el largo del período.
    # Las sumas van como promedio por día, así el mes o la semana incompleta del final no se ve como una caída.
    dias = (hasta - desde).days
    paso, nombre_paso = ('M', 'mensual') if dias > 120 else (('W', 'semanal') if dias > 21 else ('D', 'diaria'))
    por_paso = df.assign(paso=df['fecha'].dt.to_period(paso).dt.start_time)
    serie = resumen(por_paso, 'paso')
    dias_por_paso = por_paso.groupby('paso')['fecha'].nunique().values
    for col in ['entregas', 'peso_kg', 'ingreso']:
        serie[col] = serie[col] / dias_por_paso

    def linea(col):
        return serie[col].round(2).tolist() if len(serie) > 1 else None

    k = st.columns(5)
    k[0].metric('Entregas', numero(actual['entregas']), delta('entregas'), border=True,
                chart_data=linea('entregas'), chart_type='area')
    k[1].metric('A tiempo', f'{numero(actual["pct_a_tiempo"], 1)} %', delta('pct_a_tiempo', True), border=True,
                help='Entregadas hasta 30 minutos después de la hora programada',
                chart_data=linea('pct_a_tiempo'), chart_type='line')
    k[2].metric('Toneladas', numero(actual['peso_kg'] / 1000), delta('peso_kg'), border=True,
                chart_data=linea('peso_kg'), chart_type='area')
    k[3].metric('Ingreso', f'{numero(actual["ingreso"] / 1e9, 1)} mil M', delta('ingreso'), border=True,
                help='Miles de millones de pesos colombianos (COP)', chart_data=linea('ingreso'), chart_type='area')
    k[4].metric('Margen', f'{numero(actual["margen_pct"], 1)} %', delta('margen_pct', True), border=True,
                help='(ingreso − costo) / ingreso', chart_data=linea('margen_pct'), chart_type='line')
    nota = f'La línea de cada indicador muestra la evolución {nombre_paso} (las sumas, como promedio por día).'
    if previo is not None:
        nota = (f'Variación contra el mismo período un año antes ({desde_previo:%d/%m/%Y} al '
                f'{min(hasta_previo, fecha_max):%d/%m/%Y}). ' + nota)
    st.markdown(f'<div class="nota">{nota}</div>', unsafe_allow_html=True)

    # Lectura automática según los filtros
    por_ciudad = resumen(df, 'ciudad').sort_values('margen_pct')
    por_vehiculo = resumen(df, 'tipo_vehiculo').sort_values('margen_pct')
    texto = (f'la puntualidad es de <b>{numero(actual["pct_a_tiempo"], 1)} %</b> y el margen de '
             f'<b>{numero(actual["margen_pct"], 1)} %</b>. ')
    if len(por_ciudad) > 1:
        texto += (f'La ciudad más rentable es <b>{por_ciudad.iloc[-1]["ciudad"]}</b> '
                  f'({numero(por_ciudad.iloc[-1]["margen_pct"], 1)} %) y la menos rentable '
                  f'<b>{por_ciudad.iloc[0]["ciudad"]}</b> ({numero(por_ciudad.iloc[0]["margen_pct"], 1)} %). ')
    if len(por_vehiculo) > 1 and por_vehiculo.iloc[0]['margen_pct'] < 0:
        texto += (f'<b>{por_vehiculo.iloc[0]["tipo_vehiculo"]}</b> da pérdida: '
                  'su costo de combustible es tan alto como el de un camión (ver la página Flota).')
    st.write('')
    lectura(texto)

    # Entregas por mes: 2026 contra 2025 (solo meses completos)
    completos = base[(base['mes'] > base['mes'].min()) & (base['mes'] < base['mes'].max())]
    mensual = resumen(completos, 'mes')
    mensual['anio'], mensual['n_mes'] = mensual['mes'].dt.year, mensual['mes'].dt.month
    izq, der = st.columns(2)
    with izq:
        caja = tarjeta('Entregas mensuales', '2026 contra 2025 · solo meses completos')
        fig = go.Figure()
        for a, color, guiones, relleno in [(2025, GRIS, 'dash', None), (2026, AZUL, None, 'tozeroy')]:
            m = mensual[mensual['anio'] == a]
            fig.add_scatter(x=[MESES[i - 1] for i in m['n_mes']], y=m['entregas'], name=str(a), mode='lines+markers',
                            line=dict(color=color, width=2, dash=guiones, shape='spline'), marker=dict(size=6),
                            fill=relleno, fillcolor=AZUL_SUAVE,
                            hovertemplate='%{x} ' + str(a) + ': %{y:,.0f} entregas<extra></extra>')
        fig.update_xaxes(categoryorder='array', categoryarray=MESES)
        fig.update_yaxes(rangemode='tozero')
        mostrar(caja, estilo(fig, leyenda=True), para_descargar(
            mensual.assign(mes=mensual['mes'].dt.strftime('%m/%Y')),
            {'mes': 'Mes', 'entregas': 'Entregas', 'pct_a_tiempo': '% a tiempo'}), 'entregas_mensuales')
    with der:
        caja = tarjeta('Ingreso y costo mensual', 'miles de millones de COP')
        fig = go.Figure()
        fig.add_scatter(x=mensual['mes'], y=mensual['ingreso'] / 1e9, name='Ingreso', mode='lines',
                        line=dict(color=AZUL, width=2, shape='spline'), fill='tozeroy', fillcolor=AZUL_SUAVE,
                        hovertemplate='%{x|%m/%Y}: %{y:.2f}<extra>Ingreso</extra>')
        fig.add_scatter(x=mensual['mes'], y=mensual['costo'] / 1e9, name='Costo', mode='lines',
                        line=dict(color='#eb6834', width=2, shape='spline'),
                        hovertemplate='%{x|%m/%Y}: %{y:.2f}<extra>Costo</extra>')
        fig.update_xaxes(tickformat='%m/%y')
        fig.update_yaxes(rangemode='tozero')
        mostrar(caja, estilo(fig, leyenda=True), para_descargar(
            mensual.assign(mes=mensual['mes'].dt.strftime('%m/%Y'), ingreso=mensual['ingreso'] / 1e9,
                           costo=mensual['costo'] / 1e9),
            {'mes': 'Mes', 'ingreso': 'Ingreso (mil M COP)', 'costo': 'Costo (mil M COP)', 'margen_pct': 'Margen %'}),
            'ingreso_costo_mensual')
    st.markdown(f'<div class="nota">Los datos van del {fecha_min:%d/%m/%Y} al {fecha_max:%d/%m/%Y}: noviembre de 2024 y de 2026 están '
                'incompletos y no se grafican. Febrero baja porque tiene 28 días. Estos dos gráficos muestran los dos años '
                'para poder comparar, aunque arriba se elija uno.</div>', unsafe_allow_html=True)
    st.write('')

    izq, der = st.columns([2, 3])
    with izq:
        caja = tarjeta('Entregas por tipo de vehículo', 'participación')
        pv = resumen(df, 'tipo_vehiculo')
        fig = px.pie(pv, names='tipo_vehiculo', values='entregas', hole=0.6, color='tipo_vehiculo',
                     color_discrete_map=COLORES_VEHICULO)
        fig.update_traces(textinfo='percent', marker_line_color='white', marker_line_width=2,
                          hovertemplate='%{label}: %{value:,.0f} entregas<extra></extra>')
        estilo(fig, leyenda=True)
        fig.update_layout(legend=dict(orientation='h', y=-0.08, x=0.5, xanchor='center', yanchor='top'))
        mostrar(caja, fig, para_descargar(pv.assign(part=100 * pv['entregas'] / pv['entregas'].sum()),
                                          {'tipo_vehiculo': 'Tipo de vehículo', 'entregas': 'Entregas',
                                           'part': '% del total'}), 'entregas_por_vehiculo')
    with der:
        caja = tarjeta('Margen por ciudad de destino', '(ingreso − costo) / ingreso')
        pc = resumen(df, 'ciudad').sort_values('margen_pct')
        mostrar(caja, barras_horizontales(pc, 'margen_pct', 'ciudad', lambda v: f'{numero(v, 1)} %'),
                para_descargar(pc.sort_values('margen_pct', ascending=False),
                               {'ciudad': 'Ciudad', 'ingreso': 'Ingreso (COP)', 'costo': 'Costo (COP)',
                                'margen_pct': 'Margen %'}), 'margen_por_ciudad')


# ================================================================ Página: Ciudades
def pagina_ciudades():
    df = aplicar_filtros(entregas)
    encabezado('Ciudades de destino', df)
    pc = resumen(df, 'ciudad')
    pc['lat'] = pc['ciudad'].map(lambda c: COORDENADAS[c][0])
    pc['lon'] = pc['ciudad'].map(lambda c: COORDENADAS[c][1])
    lider = pc.sort_values('entregas').iloc[-1]
    lectura(f'<b>{lider["ciudad"]}</b> recibe la mayor parte de las entregas '
            f'({numero(100 * lider["entregas"] / pc["entregas"].sum(), 1)} %). La puntualidad es pareja entre ciudades; '
            'lo que cambia es el margen, porque las rutas largas consumen más combustible por entrega.')

    izq, der = st.columns([2, 3])
    with izq:
        caja = tarjeta('Mapa de entregas', 'el tamaño es la cantidad de entregas')
        fig = px.scatter_map(pc, lat='lat', lon='lon', size='entregas', size_max=45, hover_name='ciudad',
                             custom_data=['entregas', 'pct_a_tiempo', 'margen_pct'], zoom=4.3,
                             center=dict(lat=7.2, lon=-75.0), map_style='carto-positron')
        fig.update_traces(marker=dict(color=AZUL, opacity=0.75),
                          hovertemplate='<b>%{hovertext}</b><br>%{customdata[0]:,.0f} entregas<br>'
                                        '%{customdata[1]:.1f} % a tiempo<br>margen %{customdata[2]:.1f} %<extra></extra>')
        fig.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0), separators=',.')
        mostrar(caja, fig)
    with der:
        caja = tarjeta('Entregas por ciudad')
        mostrar(caja, barras_horizontales(pc.sort_values('entregas'), 'entregas', 'ciudad', lambda v: numero(v)))
        caja = tarjeta('Margen por ciudad', '(ingreso − costo) / ingreso')
        mostrar(caja, barras_horizontales(pc.sort_values('margen_pct'), 'margen_pct', 'ciudad',
                                          lambda v: f'{numero(v, 1)} %'))

    caja = tarjeta('Detalle por ciudad')
    tabla = pc.sort_values('entregas', ascending=False)[
        ['ciudad', 'entregas', 'pct_a_tiempo', 'peso_kg', 'ingreso', 'margen_pct', 'minutos_promedio']]
    # Redondeo antes y uso formato 'localized' en todas: así respeta el idioma del navegador (41.827 y 89,9 en español)
    tabla['peso_kg'] = (tabla['peso_kg'] / 1000).round(0)
    tabla['ingreso'] = (tabla['ingreso'] / 1e9).round(2)
    tabla[['pct_a_tiempo', 'margen_pct']] = tabla[['pct_a_tiempo', 'margen_pct']].round(1)
    tabla['minutos_promedio'] = tabla['minutos_promedio'].round(0)
    numero_col = lambda titulo: st.column_config.NumberColumn(titulo, format='localized')
    caja.dataframe(tabla, hide_index=True, width='stretch', column_config={
        'ciudad': 'Ciudad', 'entregas': numero_col('Entregas'), 'pct_a_tiempo': numero_col('% a tiempo'),
        'peso_kg': numero_col('Toneladas'), 'ingreso': numero_col('Ingreso (mil M COP)'),
        'margen_pct': numero_col('Margen %'), 'minutos_promedio': numero_col('Minutos por entrega')})


# ================================================================ Página: Flota
def pagina_flota():
    df = aplicar_filtros(entregas)
    encabezado('Flota', df)
    pv = resumen(df, 'tipo_vehiculo')
    pv['kg_por_entrega'] = pv['peso_kg'] / pv['entregas']
    datos_flota = para_descargar(pv.sort_values('margen_pct', ascending=False), {
        'tipo_vehiculo': 'Tipo de vehículo', 'entregas': 'Entregas', 'margen_pct': 'Margen %',
        'litros_100km': 'Litros cada 100 km', 'kg_por_entrega': 'Kilos por entrega', 'pct_a_tiempo': '% a tiempo'})
    lectura('los camiones grandes son los más rentables porque llevan más carga con un costo parecido. '
            'La <b>moto da pérdida</b> por una limitación de los datos sintéticos: el combustible se calcula solo con la '
            'distancia, así que una moto gasta lo mismo por kilómetro que un camión (≈ 11,5 L cada 100 km) '
            'pero lleva paquetes chicos. Con datos reales el consumo de una moto sería mucho menor.')
    izq, der = st.columns(2)
    with izq:
        caja = tarjeta('Margen por tipo de vehículo', '(ingreso − costo) / ingreso')
        mostrar(caja, barras_horizontales(pv.sort_values('margen_pct'), 'margen_pct', 'tipo_vehiculo',
                                          lambda v: f'{numero(v, 1)} %', colores=COLORES_VEHICULO), datos_flota, 'flota_margen_pct')
    with der:
        caja = tarjeta('Entregas por tipo de vehículo')
        mostrar(caja, barras_horizontales(pv.sort_values('entregas'), 'entregas', 'tipo_vehiculo',
                                          lambda v: numero(v), colores=COLORES_VEHICULO), datos_flota, 'flota_entregas')
    izq, der = st.columns(2)
    with izq:
        caja = tarjeta('Consumo de combustible', 'litros cada 100 km')
        mostrar(caja, barras_horizontales(pv.sort_values('litros_100km'), 'litros_100km', 'tipo_vehiculo',
                                          lambda v: numero(v, 1), colores=COLORES_VEHICULO), datos_flota, 'flota_litros_100km')
    with der:
        caja = tarjeta('Carga promedio por entrega', 'kilos')
        mostrar(caja, barras_horizontales(pv.sort_values('kg_por_entrega'), 'kg_por_entrega', 'tipo_vehiculo',
                                          lambda v: numero(v), colores=COLORES_VEHICULO), datos_flota, 'flota_kg_por_entrega')


# ================================================================ Página: Puntualidad
def pagina_puntualidad():
    df = aplicar_filtros(entregas)
    encabezado('Puntualidad', df)
    total = resumen(df).iloc[0]
    tabla = resumen(df, ['turno', 'dia']).pivot(index='turno', columns='dia', values='pct_a_tiempo')
    peor = tabla.stack().idxmin()
    lectura(f'el {numero(total["pct_a_tiempo"], 1)} % de las entregas llega a tiempo y casi no cambia según el día o el turno '
            f'(el valor más bajo es {numero(tabla.min().min(), 1)} %, el {peor[1].lower()} en el {peor[0].split(" ·")[0]}). '
            'El retraso no depende del momento de la semana, así que para mejorar hay que mirar rutas y conductores.')
    rango = tabla.max().max() - tabla.min().min()
    caja = tarjeta('% de entregas a tiempo por día y turno',
                   f'más oscuro = más puntual · entre la mejor y la peor celda hay solo {numero(rango, 1)} puntos')
    fig = px.imshow(tabla, text_auto='.1f', aspect='auto', color_continuous_scale=['#cde2fb', '#104281'])
    fig.update_traces(hovertemplate='%{x} · %{y}: %{z:.1f} % a tiempo<extra></extra>', xgap=2, ygap=2)
    datos = tabla.round(1)
    datos.columns = [str(c) for c in datos.columns]  # los días son categorías: los paso a texto para la tabla
    mostrar(caja, estilo(fig, alto=260), datos.reset_index().rename(columns={'turno': 'Turno'}), 'puntualidad_dia_turno')

    izq, der = st.columns(2)
    with izq:
        caja = tarjeta('% a tiempo por turno')
        pt = resumen(df, 'turno').sort_values('turno', ascending=False)
        mostrar(caja, barras_horizontales(pt, 'pct_a_tiempo', 'turno', lambda v: f'{numero(v, 1)} %'),
                para_descargar(pt, {'turno': 'Turno', 'entregas': 'Entregas', 'pct_a_tiempo': '% a tiempo'}),
                'puntualidad_turno')
    with der:
        caja = tarjeta('Minutos promedio por entrega', 'por ciudad de destino')
        pc = resumen(df, 'ciudad').sort_values('minutos_promedio')
        mostrar(caja, barras_horizontales(pc, 'minutos_promedio', 'ciudad', lambda v: numero(v)),
                para_descargar(pc, {'ciudad': 'Ciudad', 'entregas': 'Entregas', 'minutos_promedio': 'Minutos por entrega'}),
                'minutos_por_ciudad')


# ================================================================ Página: Conductores
def pagina_conductores():
    st.title('Conductores')
    st.markdown('<div class="nota">Todas las entregas de cada conductor (acá no se aplican los filtros de la izquierda). '
                'Solo conductores con 100 entregas o más.</div>', unsafe_allow_html=True)
    st.write('')
    c = conductores[conductores['entregas'] >= 100].assign(
        pct_a_tiempo=lambda d: 100 * d['entregas_a_tiempo'] / d['entregas'],
        margen_pct=lambda d: 100 * (d['ingreso'] - d['costo']) / d['ingreso'])
    mejor = c.sort_values('pct_a_tiempo').iloc[-1]
    lectura(f'el más puntual es <b>{mejor["conductor"]}</b> ({numero(mejor["pct_a_tiempo"], 1)} % a tiempo en '
            f'{numero(mejor["entregas"])} entregas). La categoría de desempeño (Alto / Medio / Bajo) sale de la puntualidad '
            'de los últimos 90 días, por eso no siempre coincide con el total histórico.')

    # El gráfico y el ranking van uno debajo del otro, a todo el ancho, para que la tabla entre completa
    caja = tarjeta('Entregas y puntualidad', 'cada punto es un conductor')
    fig = px.scatter(c, x='entregas', y='pct_a_tiempo', color='categoria', color_discrete_map=COLORES_CATEGORIA,
                     category_orders={'categoria': ['Alto', 'Medio', 'Bajo']}, hover_name='conductor',
                     custom_data=['zona'])
    fig.update_traces(marker=dict(size=9, opacity=0.8, line=dict(color='white', width=1)),
                      hovertemplate='<b>%{hovertext}</b> (%{customdata[0]})<br>%{x:,.0f} entregas · '
                                    '%{y:.1f} % a tiempo<extra></extra>')
    estilo(fig, alto=420, leyenda=True)
    fig.update_layout(legend_title_text='Desempeño ')
    fig.update_xaxes(title_text='Entregas en los dos años', title_font_size=11)
    fig.update_yaxes(title_text='% a tiempo', title_font_size=11)
    mostrar(caja, fig)
    caja = tarjeta('Ranking', 'los 15 primeros según el criterio elegido')
    criterio = caja.radio('Ordenar por', ['% a tiempo', 'Entregas', 'Margen'], horizontal=True,
                          label_visibility='collapsed')
    columna = {'% a tiempo': 'pct_a_tiempo', 'Entregas': 'entregas', 'Margen': 'margen_pct'}[criterio]
    ranking = c.sort_values(columna, ascending=False).head(15)[
        ['conductor', 'zona', 'entregas', 'pct_a_tiempo', 'margen_pct']].round(1)
    caja.dataframe(ranking, hide_index=True, width='stretch', height=562, column_config={
        'conductor': 'Conductor', 'zona': 'Zona',
        'entregas': st.column_config.NumberColumn('Entregas', format='localized'),
        'pct_a_tiempo': st.column_config.ProgressColumn('% a tiempo', format='localized',
                                                        min_value=80, max_value=100),
        'margen_pct': st.column_config.NumberColumn('Margen %', format='localized')})


# ================================================================ Página: Explorador (PyGWalker)
@st.cache_data(show_spinner='Preparando el explorador...')
def explorador_html(_datos, filtros):
    """Arma el explorador una vez por combinación de filtros (el guion bajo de _datos le dice a Streamlit que no lo use
    para la caché, sería lento: la clave son los filtros). Uso el modo HTML de PyGWalker, que calcula todo en el
    navegador, porque su modo para Streamlit (StreamlitRenderer) no anda con Streamlit 1.67: la versión 0.5.0.1 importa
    una función que Streamlit ya no tiene (issue 743 de Kanaries/pygwalker, arreglado pero sin publicar)."""
    import pygwalker
    pygwalker.GlobalVarManager.set_privacy('offline')  # que no mande estadísticas de uso a Kanaries
    return pygwalker.to_html(_datos, appearance='light', default_tab='vis')


def pagina_explorador():
    st.title('Explorador')
    st.markdown('<div class="nota">Armá tus propios gráficos: arrastrá columnas a los ejes X e Y, a color o a filtros. '
                'Usa los mismos datos y filtros que el resto del tablero (una fila por día, ciudad, vehículo y turno). '
                'Hecho con PyGWalker, una librería de código abierto parecida a Tableau.</div>', unsafe_allow_html=True)
    st.markdown('<div class="lectura"><b>Para empezar:</b> arrastrá <b>ciudad</b> a <i>X-Axis</i>, <b>ingreso</b> a <i>Y-Axis</i> '
                'y <b>tipo_vehiculo</b> a <i>Color</i>. Las columnas numéricas se suman; con el menú de cada campo '
                'se puede cambiar a promedio.</div>', unsafe_allow_html=True)
    st.write('')
    df = aplicar_filtros(entregas)
    if df.empty:
        st.warning('No hay entregas con esta combinación de filtros.')
        st.stop()
    datos = df.assign(fecha=df['fecha'].dt.strftime('%Y-%m-%d'), dia=df['dia'].astype(str), anio=df['anio'].astype(str),
                      mes=df['mes'].dt.strftime('%Y-%m'))
    datos = datos[['fecha', 'anio', 'mes', 'dia', 'ciudad', 'tipo_vehiculo', 'turno', 'entregas', 'entregas_a_tiempo',
                   'peso_kg', 'km', 'litros', 'ingreso', 'costo', 'minutos_entrega']]
    filtros = (desde, hasta, tuple(ciudades), tuple(vehiculos), tuple(turnos))
    # El HTML lo genero yo con PyGWalker a partir de mis datos (no viene de afuera), así que se puede embeber
    st.iframe(explorador_html(datos, filtros), height=1000)


# ================================================================ Página: Modelo de datos
def pagina_modelo():
    st.title('Modelo de datos')
    lectura('este tablero no lee la base operativa. Lee el <b>Data Warehouse en Snowflake</b> que armé en el Avance 3: '
            'un modelo estrella que el ETL actualiza todas las noches desde PostgreSQL.')
    caja = tarjeta('De dónde salen los datos')
    caja.markdown("""
1. **PostgreSQL** (Avance 1): la base operativa con 505.650 registros en 6 tablas.
2. **ETL** (`05_etl_pipeline.py`): extrae, calcula las métricas y carga en Snowflake todas las noches a las 02:00.
3. **Snowflake** (`FLEETLOGIX_DW.ANALYTICS`): `fact_deliveries` (una fila por entrega completada) y 6 dimensiones.
4. **Exportación** (`07_export_dashboard_data.py`): resume la tabla de hechos por día, ciudad, tipo de vehículo y turno,
   y la guarda en `dashboard/data/`. Así el tablero se puede abrir sin credenciales de Snowflake.
5. **Este tablero** (Streamlit): filtra y grafica esos datos.
""")
    caja = tarjeta('Modelo estrella en Snowflake')
    imagen = CARPETA.parent / '3. Documentación' / 'img' / 'modelo_estrella.png'
    if imagen.exists():
        caja.image(str(imagen), width='stretch')
    caja = tarjeta('Tablas que usa el tablero')
    caja.markdown(f"""
| Archivo | Filas | Qué tiene |
|---|---|---|
| `entregas_diarias.parquet` | {numero(len(entregas))} | entregas, a tiempo, kilos, km, litros, ingreso, costo y minutos por día, ciudad, vehículo y turno |
| `conductores.parquet` | {numero(len(conductores))} | totales de cada conductor (sumando todas sus versiones del historial SCD tipo 2) |
""")


st.navigation([
    st.Page(pagina_resumen, title='Resumen', icon=':material/dashboard:', default=True),
    st.Page(pagina_ciudades, title='Ciudades', icon=':material/location_on:', url_path='ciudades'),
    st.Page(pagina_flota, title='Flota', icon=':material/local_shipping:', url_path='flota'),
    st.Page(pagina_puntualidad, title='Puntualidad', icon=':material/schedule:', url_path='puntualidad'),
    st.Page(pagina_conductores, title='Conductores', icon=':material/badge:', url_path='conductores'),
    st.Page(pagina_explorador, title='Explorador', icon=':material/explore:', url_path='explorador'),
    st.Page(pagina_modelo, title='Modelo de datos', icon=':material/schema:', url_path='modelo'),
]).run()
