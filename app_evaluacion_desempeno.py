# -*- coding: utf-8 -*-
"""
Sistema de Evaluación del Desempeño - Gobierno del Estado de Durango
- Modo Admin (global y por dependencia) para visualizar evaluaciones.
- Modo RH (por dependencia) para capturar evaluaciones.
- Filtro principal por 'dependencia' (antes usábamos area_adscripcion).
- Nuevos campos en trabajadores: plaza, dependencia, fecha_inicio_gobierno, comisionado (texto Sí/No).
- Marca de agua institucional.
- Tooltips detallados (niveles 1–4) para 12 factores.
- Gráficas: barras por trabajador, boxplot por dependencia, línea temporal por periodo.
- Join a Supabase evaluaciones→trabajadores para traer nombre y dependencia en el panel admin.

Requiere en .streamlit/secrets.toml:
[supabase]
url = "https://XXXXXXXXXXXX.supabase.co"
key = "eyJhbGciOi..."

Autor: Tú 💪
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from supabase import create_client, Client
import unicodedata
import re
from textwrap import dedent

# ===========================================================
# CONFIGURACIÓN GENERAL
# ===========================================================
st.set_page_config(
    layout="wide",
    page_title="Sistema de Evaluación del Desempeño del Gobierno del Estado de Durango"
)

# Ocultar íconos y enlaces de Streamlit
st.markdown("""
    <style>
    #MainMenu, footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# ===========================================================
# FONDO / MARCA DE AGUA DURANGO
# ===========================================================
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    position: relative;
    z-index: 0;
}

/* 🔹 Marca de agua centrada detrás del contenido */
[data-testid="stAppViewContainer"]::before {
    content: "";
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: url("https://i.imgur.com/XMiJ2dy.jpeg");
    background-repeat: no-repeat;
    background-position: center;
    background-size: 40%;
    opacity: 0.15;
    z-index: -1;
    pointer-events: none;
}
</style>
""", unsafe_allow_html=True)

# ===========================================================
# CONEXIÓN SUPABASE
# ===========================================================
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===========================================================
# UTILIDADES
# ===========================================================
def normalizar_texto(x: str) -> str:
    """
    Normaliza texto para comparaciones robustas:
    - Quita acentos
    - Colapsa saltos/espacios
    - Minúsculas
    """
    if not isinstance(x, str):
        return ""
    x = unicodedata.normalize("NFKD", x)
    x = x.encode("ascii", "ignore").decode("utf-8")
    x = re.sub(r"[\n\r\t]+", " ", x)
    return x.strip().lower()

@st.cache_data(ttl=60)
def cargar_trabajadores() -> pd.DataFrame:
    """
    Carga la tabla 'trabajadores' completa.
    Ahora incluye: plaza, dependencia, fecha_inicio_gobierno, comisionado (texto "Sí"/"No").
    """
    try:
        res = supabase.table("trabajadores").select("*").execute()
        if not res or not res.data:
            return pd.DataFrame()
        df = pd.DataFrame(res.data)

        # Tipos suaves: metas programadas a numérico
        for c in ["meta1_prog", "meta2_prog", "meta3_prog"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        return df
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase (trabajadores): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def cargar_evaluaciones_join() -> pd.DataFrame:
    """
    Carga evaluaciones + a través de la FK 'trabajador_id' trae:
      - nombre del trabajador (como 'nombre')
      - dependencia del trabajador (como 'dependencia')
      - (opcionalmente) area_adscripcion general (como 'area_general')
    Se arma 'periodo' = mes/anio y se tipifican campos numéricos.
    """
    try:
        res = supabase.table("evaluaciones").select(
            "id,trabajador_id,dia,mes,anio,"
            "meta1_real,meta2_real,meta3_real,resultado1,resultado2,resultado3,"
            "conocimiento,criterio,calidad,tecnica,supervision,capacitacion,iniciativa,colaboracion,"
            "responsabilidad,equipo,relaciones,mejora,puntaje_total,comentarios,"
            "trabajadores:trabajador_id (id,nombre,dependencia,area_adscripcion)"
        ).execute()

        datos = res.data
        if not datos:
            return pd.DataFrame()

        filas = []
        for fila in datos:
            plano = {k: v for k, v in fila.items() if k != "trabajadores"}
            trabajador = fila.get("trabajadores", {}) or {}
            plano["nombre"] = trabajador.get("nombre")
            plano["dependencia"] = trabajador.get("dependencia")
            plano["area_general"] = trabajador.get("area_adscripcion")
            filas.append(plano)

        df = pd.DataFrame(filas)

        for c in ["dia", "mes", "anio"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

        if "puntaje_total" in df.columns:
            df["puntaje_total"] = pd.to_numeric(df["puntaje_total"], errors="coerce")

        if {"mes", "anio"} <= set(df.columns):
            df["periodo"] = df.apply(
                lambda x: f"{int(x['mes'])}/{int(x['anio'])}" if pd.notna(x["mes"]) and pd.notna(x["anio"]) else "",
                axis=1
            )

        return df
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase (evaluaciones): {e}")
        return pd.DataFrame()

# ===========================================================
# CARGA BASE
# ===========================================================
trabajadores = cargar_trabajadores()
evaluaciones_df = cargar_evaluaciones_join()

# ===========================================================
# INTERFAZ PRINCIPAL / MODOS
# ===========================================================
st.title("💼 Sistema de Evaluación del Desempeño del Gobierno del Estado de Durango")
modo = st.sidebar.radio("Selecciona el modo:", ("Superior jerárquico", "Administrador"))

# ===========================================================
# CONTROL DE ACCESOS (USUARIOS / ROLES)
# ===========================================================
roles = {
    # Admins
    "admin_global":     {"password": "admin123",      "rol": "admin_global", "area": "TODAS"},
    "admin_finanzas":   {"password": "afinanzas123",  "rol": "admin_area",   "area": "SECRETARIA DE FINANZAS Y DE ADMINISTRACION"},
    "admin_salud":      {"password": "asalud123",     "rol": "admin_area",   "area": "Secretaría de Salud"},
    "admin_educacion":  {"password": "aeducacion123", "rol": "admin_area",   "area": "Secretaría de Educación"},

    # RH
    "rh_finanzas":      {"password": "rfinanzas123",  "rol": "rh", "area": "SECRETARIA DE FINANZAS Y DE ADMINISTRACION"},
    "rh_salud":         {"password": "rsalud123",     "rol": "rh", "area": "Secretaría de Salud"},
    "rh_educacion":     {"password": "reducacion123", "rol": "rh", "area": "Secretaría de Educación"},
}

# ===========================================================
# MODO ADMINISTRADOR
# ===========================================================
if modo == "Administrador":
    usuario = st.text_input("👤 Usuario (admin_*):")
    password = st.text_input("🔒 Contraseña:", type="password")

    if usuario in roles and password == roles[usuario]["password"] and roles[usuario]["rol"].startswith("admin"):
        rol_usuario = roles[usuario]["rol"]
        dependencia_permitida = roles[usuario]["area"]

        if rol_usuario == "admin_global":
            st.subheader("📊 Panel Administrativo (Acceso Total)")
            st.success("Acceso concedido (TODAS las dependencias).")
        else:
            st.subheader(f"📊 Panel Administrativo ({dependencia_permitida})")
            st.success(f"Acceso concedido ({dependencia_permitida}).")

        df_eval = evaluaciones_df.copy()
        if df_eval.empty:
            st.warning("⚠️ No hay evaluaciones registradas.")
            st.stop()

        if rol_usuario != "admin_global":
            df_eval = df_eval[
                df_eval["dependencia"].astype(str).str.strip().str.lower() ==
                dependencia_permitida.strip().lower()
            ]

        if df_eval.empty:
            st.warning("⚠️ No hay evaluaciones registradas para esta dependencia.")
            st.stop()

        st.markdown("### 🔍 Filtros de búsqueda")
        col1, col2, col3, col4 = st.columns(4)

        nombres_disp = sorted(df_eval["nombre"].dropna().unique().tolist())
        filtro_nombre = col1.selectbox("Filtrar por nombre", ["(Todos)"] + nombres_disp)

        if rol_usuario == "admin_global":
            dependencias_disp = sorted(df_eval["dependencia"].dropna().unique().tolist())
            filtro_dependencia = col2.selectbox("Filtrar por dependencia", ["(Todas)"] + dependencias_disp)
        else:
            filtro_dependencia = dependencia_permitida

        areas_disp = sorted(df_eval["area_general"].dropna().unique().tolist()) if "area_general" in df_eval.columns else []
        filtro_area = col3.selectbox("Filtrar por área de adscripción", ["(Todas)"] + areas_disp)

        puestos_disp = []
        if "trabajador_id" in df_eval.columns and not trabajadores.empty:
            puestos_merge = df_eval.merge(
                trabajadores[["id", "puesto"]],
                left_on="trabajador_id", right_on="id", how="left"
            )
            df_eval["puesto"] = puestos_merge["puesto"]
            puestos_disp = sorted(puestos_merge["puesto"].dropna().unique().tolist())
        filtro_puesto = col4.selectbox("Filtrar por puesto", ["(Todos)"] + puestos_disp)

        if filtro_nombre != "(Todos)":
            df_eval = df_eval[df_eval["nombre"] == filtro_nombre]
        if rol_usuario == "admin_global" and filtro_dependencia != "(Todas)":
            df_eval = df_eval[df_eval["dependencia"] == filtro_dependencia]
        if filtro_area != "(Todas)" and "area_general" in df_eval.columns:
            df_eval = df_eval[df_eval["area_general"] == filtro_area]
        if filtro_puesto != "(Todos)" and "puesto" in df_eval.columns:
            df_eval = df_eval[df_eval["puesto"] == filtro_puesto]

        st.caption(f"🔎 Resultados filtrados: {len(df_eval)} registros")
        if df_eval.empty:
            st.warning("⚠️ No hay evaluaciones que coincidan con los filtros seleccionados.")
            st.stop()

        if "puntaje_total" in df_eval.columns:
            promedio_general = round(pd.to_numeric(df_eval["puntaje_total"], errors="coerce").mean(), 2)
            total_evals = len(df_eval)
            st.markdown(
                f"### 📈 Promedio general: **{promedio_general}/48** &nbsp;&nbsp; _(Total de evaluaciones: {total_evals})_"
            )
        else:
            st.info("ℹ️ No se encontró 'puntaje_total' para calcular el promedio.")

        colg1, colg2, colg3 = st.columns(3)

        with colg1:
            if {"nombre", "puntaje_total"} <= set(df_eval.columns):
                fig1 = px.bar(
                    df_eval, x="nombre", y="puntaje_total",
                    color="dependencia",
                    text="puntaje_total",
                    title="Puntaje total por trabajador"
                )
                fig1.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig1.update_layout(xaxis_title="Trabajador", yaxis_title="Puntaje total")
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.warning("⚠️ No se encontró 'nombre' o 'puntaje_total' para la gráfica de barras.")

        with colg2:
            if {"dependencia", "puntaje_total"} <= set(df_eval.columns):
                fig2 = px.box(
                    df_eval, x="dependencia", y="puntaje_total",
                    title="Distribución del puntaje por dependencia"
                )
                fig2.update_layout(xaxis_title="Dependencia", yaxis_title="Puntaje total")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("⚠️ No se encontró 'dependencia' o 'puntaje_total' para la gráfica por dependencia.")

        with colg3:
            if {"periodo", "puntaje_total"} <= set(df_eval.columns):
                ordenado = df_eval.sort_values(["anio", "mes"])
                fig3 = px.line(
                    ordenado, x="periodo", y="puntaje_total",
                    color="nombre" if "nombre" in ordenado.columns else None,
                    markers=True,
                    title="Evolución del puntaje total (por mes/año)"
                )
                fig3.update_layout(xaxis_title="Periodo", yaxis_title="Puntaje total")
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.warning("⚠️ No se encontró 'periodo' para la gráfica temporal.")

        st.markdown("#### 📄 Evaluaciones (detalle filtrado)")
        mostrar_cols = [c for c in [
            "id", "trabajador_id", "nombre", "dependencia", "area_general", "puesto",
            "dia", "mes", "anio",
            "meta1_real", "meta2_real", "meta3_real",
            "resultado1", "resultado2", "resultado3",
            "conocimiento", "criterio", "calidad", "tecnica", "supervision", "capacitacion",
            "iniciativa", "colaboracion", "responsabilidad", "equipo", "relaciones", "mejora",
            "puntaje_total", "comentarios"
        ] if c in df_eval.columns]
        st.dataframe(df_eval[mostrar_cols], use_container_width=True)

    elif password != "":
        st.error("❌ Credenciales incorrectas o usuario sin rol de administrador.")

# ===========================================================
# MODO RH
# ===========================================================
elif modo == "Superior jerárquico":
    usuario = st.text_input("👤 Usuario (rh_*):")
    password = st.text_input("🔒 Contraseña:", type="password")

    if usuario in roles and password == roles[usuario]["password"] and roles[usuario]["rol"] == "rh":
        dependencia_rh = roles[usuario]["area"]
        st.subheader(f"🧾 Evaluación: {dependencia_rh}")
        st.success(f"Acceso concedido (solo puedes evaluar personal de {dependencia_rh}).")

        if trabajadores.empty:
            st.warning("⚠️ No hay datos en la tabla 'trabajadores'.")
            st.stop()

        if "dependencia" not in trabajadores.columns:
            st.error("❌ La columna 'dependencia' no existe en la tabla 'trabajadores'. Verifica el esquema.")
            st.stop()

        trabajadores_filtrados = trabajadores[
            trabajadores["dependencia"].astype(str).str.strip().str.lower() ==
            dependencia_rh.strip().lower()
        ]
        if trabajadores_filtrados.empty:
            st.warning("⚠️ No hay trabajadores registrados para tu dependencia.")
            st.stop()

        trabajadores_unicos = trabajadores_filtrados.drop_duplicates(subset=["nombre"])
        lista_nombres = trabajadores_unicos["nombre"].dropna().sort_values().tolist()
        seleccionado = st.selectbox("Selecciona un trabajador:", lista_nombres)
        trab = trabajadores_unicos[trabajadores_unicos["nombre"] == seleccionado].iloc[0]
        ctx = f"trab_{int(trab['id'])}"

        # ---------------- DATOS PERSONALES ----------------
        st.subheader("Datos Personales")
        cols = st.columns(2)
        campos = [
            "nombre", "curp", "rfc", "superior",
            "dependencia", "area_adscripcion",
            "puesto", "nivel", "plaza",
            "fecha_inicio_gobierno", "antig_puesto", "antig_gob",
            "comisionado", "area_comision"
        ]
        etiquetas = [
            "Nombre", "CURP", "RFC", "Superior",
            "Dependencia", "Área (general)",
            "Puesto", "Nivel", "Plaza",
            "Fecha de inicio en Gobierno", "Antigüedad en Puesto", "Antigüedad en Gobierno",
            "Comisionado (Sí/No)", "Área de comisión"
        ]
        for i, campo in enumerate(campos):
            valor = trab.get(campo, "")
            cols[i % 2].text_input(etiquetas[i], "" if pd.isna(valor) else str(valor), disabled=True)

        # ---------------- FUNCIONES Y METAS ----------------
        st.subheader("Actividades Principales")
        for i in range(1, 4):
            st.text_input(
                f"Actividad {i}",
                value=str(trab.get(f"funcion{i}", "") or ""),
                disabled=True,
                key=f"{ctx}_actividad_{i}"
            )

        st.subheader("Metas (avance por tramo)")

        # --- Estilos para bloques tipo "card" (metas) ---
        st.markdown("""
        <style>
        .meta-title{
            font-size:20px;
            font-weight:900;
            color:#111;
            letter-spacing:.2px;
            margin: 10px 0 6px 0;
        }
        .meta-caption{
            margin: 0 0 10px 0;
            color: rgba(0,0,0,.60);
            font-size: 13px;
        }
        .sel-slot{
            height: 22px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .sel-badge{
            display: inline-block;
            font-size: 11px;
            font-weight: 800;
            border: 1px solid rgba(0,0,0,.18);
            border-radius: 999px;
            padding: 2px 10px;
            background: rgba(255,255,255,.85);
            white-space: nowrap;
        }
        .cell-marker{ height: 0; }

        /* Botón base en forma de tarjeta */
        .meta-cards button{
            width: 100% !important;
            text-align: left !important;
            white-space: normal !important;
            line-height: 1.25em !important;
            padding: 12px 12px !important;
            border-radius: 12px !important;
            border: 1px solid rgba(0,0,0,.12) !important;
            background: rgba(255,255,255,.90) !important;
            min-height: 82px !important;
        }

        /* Selección por nivel (colores) */
        .meta-cards div:has(> div > .cell-marker.meta-1) button{
            border: 2px solid #8B2E2E !important;
            background: rgba(139,46,46,.06) !important;
        }
        .meta-cards div:has(> div > .cell-marker.meta-2) button{
            border: 2px solid #B08900 !important;
            background: rgba(176,137,0,.07) !important;
        }
        .meta-cards div:has(> div > .cell-marker.meta-3) button{
            border: 2px solid #1F4E79 !important;
            background: rgba(31,78,121,.06) !important;
        }
        .meta-cards div:has(> div > .cell-marker.meta-4) button{
            border: 2px solid #2E7D32 !important;
            background: rgba(46,125,50,.07) !important;
        }
        </style>
        """, unsafe_allow_html=True)

        st.markdown(
            """
            <style>
            /* ===== Mejora tipográfica (sobrescribe lo anterior) ===== */

            /* Subtítulos (st.subheader -> h2) */
            [data-testid="stMarkdownContainer"] h2,
            [data-testid="stMarkdownContainer"] h3 {
                font-size: 40px !important;
                font-weight: 800 !important;
                text-align: center !important;
            }


            /* Si llegas a usar h3 */
            h3{
                font-size: 22px !important;
                font-weight: 700 !important;
                text-align: center !important;
                margin-top: 25px !important;
                margin-bottom: 20px !important;
            }

            /* Metas: jerarquía */
            .meta-title{
                font-size: 20px;
                font-weight: 800;
                color: #1a1a1a;
                letter-spacing: .3px;
                margin-bottom: 4px;
            }

            .meta-caption{
                font-size: 13px;
                font-weight: 500;
                color: rgba(0,0,0,.55);
                margin-bottom: 18px;
            }

            .meta-resumen{
                font-size: 16px;
                font-weight: 800;
                margin-top: 14px;
                margin-bottom: 4px;
            }

            .meta-unidades{
                font-size: 13px;
                color: rgba(0,0,0,.65);
                margin-bottom: 16px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        def meta_bloques(ctx: str, meta_idx: int, desc: str, prog: float, default_level: int = 1):
            """
            Devuelve:
              - nivel (1..4)
              - min_pct, max_pct (rango seleccionado)
              - pct_guardado (valor para guardar en DB: 25/50/75/100)
            """
            state_key = f"meta_{ctx}_{meta_idx}_nivel"
            if state_key not in st.session_state:
                st.session_state[state_key] = int(default_level)

            seleccionado = int(st.session_state[state_key])

            # (label, nivel, min_pct, max_pct, pct_guardado, help)
            niveles = [
                ("0–25% | Avance mínimo",           1, 0, 25, 25,   "Avance muy limitado respecto a lo programado."),
                ("26–50% | Avance parcial",         2, 26, 50, 50,  "Existe avance, pero aún distante de la meta."),
                ("51–75% | Avance significativo",   3, 51, 75, 75,  "Progreso importante; aún no se alcanza completamente."),
                ("76–100% | Meta alcanzada",        4, 76, 100, 100, "La meta se cumple conforme a lo programado o se supera."),
            ]

            def _set_level(sk: str, val: int):
                st.session_state[sk] = int(val)

            st.markdown(f'<div class="meta-title">Meta {meta_idx}: {desc}</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="meta-caption">Programada: {prog:g}</div>' if prog
                else '<div class="meta-caption">Programada: 0 (sin dato / no aplica)</div>',
                unsafe_allow_html=True
            )

            c1, c2, c3, c4 = st.columns(4)
            cols = [c1, c2, c3, c4]

            for j, (label, nivel, min_pct, max_pct, pct_guardado, help_txt) in enumerate(niveles):
                with cols[j]:
                    if seleccionado == nivel:
                        color = {1: "#8B2E2E", 2: "#B08900", 3: "#1F4E79", 4: "#2E7D32"}[nivel]
                        st.markdown(
                            f"""
                            <div class="sel-slot">
                                <span class="sel-badge" style="border-color:{color}; color:{color};">
                                    Nivel {nivel}
                                </span>
                                <span style="flex:1; height:0; border-top:3px solid {color}; opacity:.9;"></span>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        st.markdown(f'<div class="cell-marker meta-{nivel}"></div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="sel-slot"></div>', unsafe_allow_html=True)
                        st.markdown('<div class="cell-marker"></div>', unsafe_allow_html=True)

                    st.button(
                        label,
                        key=f"btn_{ctx}_meta{meta_idx}_{nivel}",
                        help=help_txt,
                        use_container_width=True,
                        on_click=_set_level,
                        args=(state_key, nivel),
                    )

            nivel_final = int(st.session_state[state_key])
            min_pct, max_pct, pct_guardado = next(
                (mn, mx, pg) for (_, n, mn, mx, pg, _,) in niveles if n == nivel_final
            )

            return nivel_final, int(min_pct), int(max_pct), float(pct_guardado)
        st.markdown('<div class="meta-cards">', unsafe_allow_html=True)
        meta_real, resultados = {}, {}

        for i in range(1, 4):
            desc = trab.get(f"meta{i}_desc", "") or "Sin descripción"
            prog_val = trab.get(f"meta{i}_prog", 0)

            try:
                prog = float(prog_val) if prog_val not in ("", None) else 0.0
            except Exception:
                prog = 0.0

            nivel_sel, min_pct, max_pct, pct_guardado = meta_bloques(
                ctx=ctx, meta_idx=i, desc=desc, prog=prog, default_level=1
            )

            # Guardado numérico (DB)
            resultados[f"resultado{i}"] = float(pct_guardado)
            meta_real[f"meta{i}_real"] = float(prog) * (pct_guardado / 100.0) if prog else 0.0

            # Calcular equivalente en unidades (min–max) para mostrar en UI
            if prog:
                min_val = prog * (min_pct / 100.0)
                max_val = prog * (max_pct / 100.0)

            # Mostrar rango en UI (sin caja azul)
            st.markdown(
                f'<div class="meta-resumen">'
                f'Nivel {nivel_sel} · {min_pct}–{max_pct}%'
                f'</div>',
                unsafe_allow_html=True
            )

            if prog:
                st.markdown(
                    f'<div class="meta-unidades">'
                    f'Equivalente: {min_val:.2f} – {max_val:.2f} de {prog:g}'
                    f'</div>',
                    unsafe_allow_html=True
                )

            st.divider()
        st.markdown('</div>', unsafe_allow_html=True)
        # ===========================================================
        # FACTORES DE CALIDAD (MATRIZ = selección + glosa por celda)
        # (UNA SOLA VEZ POR EVALUACIÓN)
        # ===========================================================
        st.markdown('<div class="factor-cards">', unsafe_allow_html=True)
        st.subheader("Factores de Calidad")
        st.markdown("""
        <style>
        .factor-title{
            font-size:17px;
            font-weight:900;
            color:#111;
            letter-spacing:.2px;
            margin: 10px 0 8px 0;
        }

        .sel-slot{
            height: 22px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .sel-badge{
            display: inline-block;
            font-size: 11px;
            font-weight: 800;
            border: 1px solid rgba(0,0,0,.18);
            border-radius: 999px;
            padding: 2px 10px;
            background: rgba(255,255,255,.85);
            white-space: nowrap;
        }

        .cell-marker{
            height: 0;
        }

        /* Botón base */
        .factor-cards button{
            width: 100% !important;
            text-align: left !important;
            white-space: normal !important;
            line-height: 1.25em !important;
            padding: 10px 12px !important;
            border-radius: 12px !important;
            border: 1px solid rgba(0,0,0,.12) !important;
            background: rgba(255,255,255,.85) !important;
            min-height: 82px !important;
        }

        /* NIVEL 1 */
        .factor-cards div:has(> div > .cell-marker.nivel-1) button{
            border: 2px solid #8B2E2E !important;
            background: rgba(139,46,46,.06) !important;
        }

        /* NIVEL 2 */
        .factor-cards div:has(> div > .cell-marker.nivel-2) button{
            border: 2px solid #B08900 !important;
            background: rgba(176,137,0,.07) !important;
        }

        /* NIVEL 3 */
        .factor-cards div:has(> div > .cell-marker.nivel-3) button{
            border: 2px solid #1F4E79 !important;
            background: rgba(31,78,121,.06) !important;
        }

        /* NIVEL 4 */
        .factor-cards div:has(> div > .cell-marker.nivel-4) button{
            border: 2px solid #2E7D32 !important;
            background: rgba(46,125,50,.07) !important;
        }
        </style>
        """, unsafe_allow_html=True)


        # -----------------------------------------------------------
        # DESCRIPCIONES COMPLETAS (12 factores x 4 niveles)
        # - resumen: lo visible en la celda
        # - completo: lo que aparece en help= (glosa por celda)
        # -----------------------------------------------------------
        descripciones = {
            "CONOCIMIENTO DEL PUESTO": [
                {
                    "resumen": "1. Conoce solo partes; requiere orientación constante.",
                    "completo": "POSEE MÍNIMOS CONOCIMIENTOS DEL PUESTO QUE TIENE ASIGANDO, LO QUE LE IMPIDE CUMPLIR CON LA OPORTUNIDAD Y CALIDAD ESTABLECIDA PARA LA PRESTACIÓN DE LOS SERVICIOS QUE TIENE ENCOMENDADOS."
                },
                {
                    "resumen": "2. Conocimiento elemental; resuelve rutinas con apoyo.",
                    "completo": "POSEE CONOCIMIENTOS ELEMENTALES DEL PUESTO QUE TIENE ASIGNADO, LO QUE PROVOCA, EN LA PRESTACIÓN DE LOS SERVICIOS QUE TIENE ENCOMENDADOS, DEFICIENCIAS EN LA OPORTUNIDAD Y CALIDAD BÁSICAS ESTABLECIDAS."
                },
                {
                    "resumen": "3. Conoce adecuadamente; opera con autonomía en la mayoría.",
                    "completo": "POSEE UN REGULAR CONOCIMIENTO DEL PUESTO QUE TIENE ASIGNADO, LO QUE LE PERMITE PRESTAR LOS SERVICIOS QUE TIENE ENCOMENDADOS CON UNA OPORTUNIDAD Y CALIDAD BÁSICAS."
                },
                {
                    "resumen": "4. Dominio amplio; asesora y anticipa impactos.",
                    "completo": "POSEE AMPLIOS CONOCIMIENTOS DEL PUESTO QUE TIENE ASIGNADO, LO QUE LE PERMITE PRESTAR LOS SERVICIOS QUE TIENE ENCOMENDADOS CON LA OPORTUNIDAD Y CALIDAD REQUERIDAS."
                },
            ],
        
            "CRITERIO": [
                {
                    "resumen": "1. Decide sin fundamento; no contrasta evidencias.",
                    "completo": "PROPONE SOLUCIONES IRRELEVANTES A LOS PROBLEMAS DE TRABAJO QUE SE LE PRESENTAN."
                },
                {
                    "resumen": "2. Decide con información básica; ignora variables a veces.",
                    "completo": "PROPONE SOLUCIONES ACEPTABLES A LOS PROBLEMAS DE TRABAJO QUE SE LE PRESENTAN."
                },
                {
                    "resumen": "3. Analiza alternativas; pide apoyo en casos complejos.",
                    "completo": "PROPONE SOLUCIONES ADECUADAS A LOS PROBLEMAS DE TRABAJO QUE SE LE PRESENTAN."
                },
                {
                    "resumen": "4. Diagnóstico sólido; pondera riesgos y documenta.",
                    "completo": "PROPONE SOLUCIONES ÓPTIMAS A LOS PROBLEMAS DE TRABAJO QUE SE LE PRESENTAN."
                },
            ],
        
            "CALIDAD DEL TRABAJO": [
                {
                    "resumen": "1. Entregables con errores; requiere rehacer frecuentemente.",
                    "completo": "REALIZA TRABAJOS CON ALTO ÍNDICE DE ERRORES EN SU CONFIABILIDAD, EXACTITUD Y PRESENTACIÓN."
                },
                {
                    "resumen": "2. Calidad aceptable pero irregular; errores periódicos.",
                    "completo": "REALIZA TRABAJOS REGULARES CON ALGUNOS ERRORES EN SU CONFIABILIDAD, EXACTITUD Y PRESENTACIÓN."
                },
                {
                    "resumen": "3. Entregables correctos y oportunos; errores esporádicos.",
                    "completo": "REALIZA BUENOS TRABAJOS Y EXCEPCIONALMENTE COMETE ERRORES EN SU CONFIABILIDAD, EXACTITUD Y PRESENTACIÓN."
                },
                {
                    "resumen": "4. Alta calidad sostenida; estandariza buenas prácticas.",
                    "completo": "REALIZA TRABAJOS EXCELENTES SIN COMETER ERRORES EN SU CONFIABILIDAD, EXACTITUD Y PRESENTACIÓN."
                },
            ],
        
            "TÉCNICA Y ORGANIZACIÓN DEL TRABAJO": [
                {
                    "resumen": "1. Sin métodos ni controles; desorden en archivos y tiempos.",
                    "completo": "APLICA EN GRADO MÍNIMO LAS TÉCNICAS Y LA ORGANIZACIÓN ESTABLECIDAS PARA EL DESARROLLO DE SU TRABAJO."
                },
                {
                    "resumen": "2. Técnicas básicas intermitentes; documentación incompleta.",
                    "completo": "APLICA OCASIONALMENTE LAS TÉCNICAS Y LA ORGANIZACIÓN ESTABLECIDAS PARA EL DESARROLLO DE SU TRABAJO."
                },
                {
                    "resumen": "3. Planifica y controla avances; documenta evidencias.",
                    "completo": "APLICA GENERALMENTE LAS TÉCNICAS Y LA ORGANIZACIÓN ESTABLECIDAS PARA EL DESARROLLO DE SU TRABAJO."
                },
                {
                    "resumen": "4. Optimiza flujos; diseña checklists y reduce riesgos.",
                    "completo": "APLICA LA MAYORÍA DE LAS VECES LAS TÉCNICAS Y LA ORGANIZACIÓN ESTABLECIDAS PARA EL DESARROLLO DE SU TRABAJO."
                },
            ],
        
            "NECESIDAD DE SUPERVISIÓN": [
                {
                    "resumen": "1. Requiere seguimiento permanente; no avanza sin indicaciones.",
                    "completo": "REQUIERE PERMANENTE SUPERVISIÓN PARA REALIZAR LAS FUNCIONES QUE TIENE ENCOMENDADAS DE ACUERDO CON EL PERFIL DE PUESTO."
                },
                {
                    "resumen": "2. Requiere supervisión ocasional en hitos clave.",
                    "completo": "REQUIERE OCASIONAL SUPERVISIÓN PARA REALIZAR LAS FUNCIONES QUE TIENE ENCOMENDADAS DE ACUERDO CON EL PERFIL DE PUESTO."
                },
                {
                    "resumen": "3. Mínima supervisión; reporta avances y pide revisión crítica.",
                    "completo": "REQUIERE MÍNIMA SUPERVISIÓN PARA REALIZAR LAS FUNCIONES QUE TIENE ENCOMENDADAS DE ACUERDO CON EL PERFIL DE PUESTO."
                },
                {
                    "resumen": "4. Autonomía; propone objetivos y solicita validación final.",
                    "completo": "REQUIERE NULA SUPERVISIÓN PARA REALIZAR LAS FUNCIONES QUE TIENE ENCOMENDADAS DE ACUERDO CON EL PERFIL DE PUESTO."
                },
            ],
        
            "CAPACITACIÓN RECIBIDA": [
                {
                    "resumen": "1. No aplica contenidos; sin evidencia de mejora.",
                    "completo": "APLICA MÍNIMAMENTE EN EL TRABAJO LOS CONOCIMIENTOS ADQUIRIDOS MEDIANTE LA CAPACITACIÓN, LO QUE LE IMPIDE ELEVAR LA EFICIENCIA Y EFICACIA DE SU TRABAJO."
                },
                {
                    "resumen": "2. Aplica parcialmente; requiere recordatorios frecuentes.",
                    "completo": "APLICA LIMITADAMENTE LOS CONOCIMIENTOS ADQUIRIDOS MEDIANTE LA CAPACITACIÓN, LO QUE LE PERMITE ELEVAR ESCASAMENTE LA EFICIENCIA Y EFICACIA DE SU TRABAJO."
                },
                {
                    "resumen": "3. Integra aprendizajes; mejora en tiempos y calidad.",
                    "completo": "APLICA SUFICIENTEMENTE LOS CONOCIMIENTOS ADQUIRIDOS MEDIANTE LA CAPACITACIÓN, LO QUE LE PERMITE ELEVAR MEDIANAMENTE LA EFICIENCIA Y EFICACIA DE SU TRABAJO."
                },
                {
                    "resumen": "4. Difunde buenas prácticas; capacita y mejora procesos.",
                    "completo": "APLICA AMPLIAMENTE LOS CONOCIMIENTOS ADQUIRIDOS MEDIANTE LA CAPACITACIÓN, LO QUE LE PERMITE ELEVAR EN GRADO MÁXIMO LA EFICIENCIA Y EFICACIA DE SU TRABAJO."
                },
            ],
        
            "INICIATIVA": [
                {
                    "resumen": "1. Se limita a lo solicitado; evita proponer mejoras.",
                    "completo": "REALIZA NULAS APORTACIONES PARA EL MEJORAMIENTO DE SU TRABAJO, POR LO QUE NO CONTRIBUYE A LA DISMINUCIÓN DE LOS TIEMPOS NI AL AUMENTO DE LA CALIDAD EN LA PRESTACIÓN DE LOS SERVICIOS."
                },
                {
                    "resumen": "2. Propone ideas puntuales; apoya mejoras simples si se le pide.",
                    "completo": "REALIZA IRRELEVANTES APORTACIONES PARA EL MEJORAMIENTO DEL TRABAJO, LO CUAL PROVOCA UN MÍNIMO IMPACTO EN LA DISMINUCIÓN DE LOS TIEMPOS Y EL AUMENTO DE LA CALIDAD EN LA PRESTACIÓN DE LOS SERVICIOS."
                },
                {
                    "resumen": "3. Detecta oportunidades y propone acciones concretas.",
                    "completo": "REALIZA APORTACIONES PARA EL MEJORAMIENTO DEL TRABAJO, LO CUAL CONTRIBUYE A LA DISMINUCIÓN DE LOS TIEMPOS Y EL AUMENTO DE LA CALIDAD EN LA PRESTACIÓN DE LOS SERVICIOS."
                },
                {
                    "resumen": "4. Impulsa mejoras continuas; institucionaliza cambios.",
                    "completo": "REALIZA APORTACIONES DESTACADAS PARA EL MEJORAMIENTO DEL TRABAJO, LO CUAL CONTRIBUYE A LAS DISMINUCIÓN DE LOS TIEMPOS Y EL AUMENTO DE LA CALIDAD EN LA PRESTACIÓN DE LOS SERVICIOS."
                },
            ],
        
            "COLABORACIÓN Y DISCRECIÓN": [
                {
                    "resumen": "1. Baja cooperación; maneja mal información; genera conflictos.",
                    "completo": "MUESTRA NULA DISPOSICIÓN PARA COLABORAR EN LA REALIZACIÓN DEL TRABAJO Y PROVOCA CONFLICTOS CON LA INFORMACIÓN QUE MANEJA."
                },
                {
                    "resumen": "2. Colabora irregular; discreción aceptable con lapsos.",
                    "completo": "MUESTRA REGULAR DISPOSICIÓN PARA COLABORAR EN LA REALIZACIÓN DEL TRABAJO Y COMETE INDISCRECIONES INVOLUNTARIAS CON LA INFORMACIÓN QUE MANEJA."
                },
                {
                    "resumen": "3. Buena cooperación; manejo prudente de información sensible.",
                    "completo": "MUESTRA BUENA DISPOSICIÓN PARA COLABORAR EN LA REALIZACIÓN DEL TRABAJO Y ES PRUDENTE CON LA INFORMACIÓN QUE MANEJA."
                },
                {
                    "resumen": "4. Colabora proactivamente; confidencialidad impecable.",
                    "completo": "MUESTRA NOTABLE DISPOSICIÓN PARA COLABORAR EN LA REALIZACIÓN DEL TRABAJO Y SABE UTILIZAR POSITIVAMENTE LA INFORMACIÓN QUE MANEJA."
                },
            ],
        
            "RESPONSABILIDAD Y DISCIPLINA": [
                {
                    "resumen": "1. Incumple plazos y normas; requiere llamados de atención.",
                    "completo": "CUMPLE MÍNIMAMANETE CON LOS OBJETIVOS Y METAS INSTITUCIONALES Y EVADE SIEMPRE LAS DISPOSICIONES ESTABLECIDAS."
                },
                {
                    "resumen": "2. Cumple parcialmente; respeta normas con recordatorios.",
                    "completo": "CUMPLE OCASIONALMENTE CON LOS OBJETIVOS Y METAS INSTITUCIONALES, Y CON FRECUENCIA MANIFIESTA INCONFORMIDAD CON LAS DISPOSICIONES ESTABLECIDAS."
                },
                {
                    "resumen": "3. Cumple metas y disposiciones; puntual y confiable.",
                    "completo": "CUMPLE LA MAYORÍA DE LAS VECES CON LOS OBJETIVOS Y METAS INSTITUCIONALES, AUNQUE EN ALGUNAS OCASIONES OBJETA LAS DISPOSICIONES ESTABLECIDAS."
                },
                {
                    "resumen": "4. Excede metas con apego normativo; lidera con el ejemplo.",
                    "completo": "CUMPLE INVARIABLEMENTE CON LOS OBJETIVOS Y METAS INSTITUCIONALES Y SIEMPRE SE SUJETA A LAS INSTRUCCIONES O DISPOSICIONES ESTABLECIDAS."
                },
            ],
        
            "TRABAJO EN EQUIPO": [
                {
                    "resumen": "1. Dificulta coordinación; poca apertura al consenso.",
                    "completo": "MANIFIESTA NULA DISPOSICIÓN PARA COLABORAR EN EQUIPO Y COMO MIEMBRO DEL EQUIPO, ENTORPECE LOS TRABAJOS DEL MISMO."
                },
                {
                    "resumen": "2. Coopera cuando se solicita; apertura moderada.",
                    "completo": "MANIFIESTA REGULAR DISPOSICIÓN, PARA TRABAJAR EN EQUIPO Y COMO MIEMBRO DEL EQUIPO, ES UN ELEMENTO QUE INTERFIERE A LA ACCIÓN DEL MISMO."
                },
                {
                    "resumen": "3. Colabora activamente; comparte información; busca acuerdos.",
                    "completo": "MANIFIESTA BUENA DISPOSICIÓN, PARA TRABAJAR EN EQUIPO Y COMO MIEMBRO DEL EQUIPO, ES UN ELEMENTO QUE BENEFICIA A LA EFICIENCIA DEL MISMO."
                },
                {
                    "resumen": "4. Integra voluntades; facilita acuerdos y resultados conjuntos.",
                    "completo": "MANIFIESTA NOTABLE DISPOSICIÓN, PARA TRABAJAR EN EQUIPO Y COMO MIEMBRO DEL EQUIPO, ES UN ELEMENTO FUNDAMENTAL PARA LA EFICIENCIA DEL MISMO."
                },
            ],
        
            "RELACIONES INTERPERSONALES": [
                {
                    "resumen": "1. Trato deficiente; conflictos frecuentes; baja escucha.",
                    "completo": "MANTIENE NULO GRADO DE INTERACCIÓN CON JEFES, COMPAÑEROS Y PÚBLICO."
                },
                {
                    "resumen": "2. Trato correcto con áreas de mejora; escucha parcial.",
                    "completo": "MANTIENE REGULAR GRADO DE INTERACCIÓN CON JEFES, COMPAÑEROS Y PÚBLICO."
                },
                {
                    "resumen": "3. Interacción respetuosa y efectiva; escucha activa.",
                    "completo": "MANTIENE BUEN GRADO DE INTERACCIÓN CON JEFES, COMPAÑEROS Y PÚBLICO."
                },
                {
                    "resumen": "4. Excelente trato; empatía; resuelve tensiones constructivamente.",
                    "completo": "MANTIENE EXCELENTE GRADO DE INTERACCIÓN CON JEFES, COMPAÑEROS Y PÚBLICO."
                },
            ],
        
            "MEJORA CONTINUA": [
                {
                    "resumen": "1. No identifica mejoras; estanca procesos.",
                    "completo": "DEMUESTRA MÍNIMO COMPROMISO PARA IDENTIFICAR ÁREAS DE OPORTUNIDAD Y PROPONER MEJORAS, CON LA FINALIDAD DE ALCANZAR LOS OBJETIVOS Y METAS INSTITUCIONALES."
                },
                {
                    "resumen": "2. Identifica mejoras puntuales; ejecución parcial.",
                    "completo": "DEMUESTRA REGULAR COMPROMISO PARA IDENTIFICAR ÁREAS DE OPORTUNIDAD Y PROPONER MEJORAS, CON LA FINALIDAD DE ALCANZAR LOS OBJETIVOS Y METAS INSTITUCIONALES."
                },
                {
                    "resumen": "3. Identifica y ejecuta mejoras con impacto observable.",
                    "completo": "DEMUESTRA BASTANTE COMPROMISO PARA IDENTIFICAR ÁREAS DE OPORTUNIDAD Y PROPONER MEJORAS, CON LA FINALIDAD DE ALCANZAR LOS OBJETIVOS Y METAS INSTITUCIONALES."
                },
                {
                    "resumen": "4. Mejora sistemáticamente; mide resultados y consolida estándares.",
                    "completo": "DEMUESTRA AMPLIO COMPROMISO PARA IDENTIFICAR ÁREAS DE OPORTUNIDAD Y PROPONER MEJORAS, CON LA FINALIDAD DE ALCANZAR LOS OBJETIVOS Y METAS INSTITUCIONALES."
                },
            ],
        }


        # ===========================================================
        # MAPEO FACTORES (UI -> COLUMNAS SUPABASE)
        # ===========================================================
        map_factores = {
            "CONOCIMIENTO DEL PUESTO": "conocimiento",
            "CRITERIO": "criterio",
            "CALIDAD DEL TRABAJO": "calidad",
            "TÉCNICA Y ORGANIZACIÓN DEL TRABAJO": "tecnica",
            "NECESIDAD DE SUPERVISIÓN": "supervision",
            "CAPACITACIÓN RECIBIDA": "capacitacion",
            "INICIATIVA": "iniciativa",
            "COLABORACIÓN Y DISCRECIÓN": "colaboracion",
            "RESPONSABILIDAD Y DISCIPLINA": "responsabilidad",
            "TRABAJO EN EQUIPO": "equipo",
            "RELACIONES INTERPERSONALES": "relaciones",
            "MEJORA CONTINUA": "mejora",
        }

        # ===========================================================
        # UTILIDADES DE FACTORES DE CALIDAD
        # ===========================================================
        # ===========================================================
        # ===========================================================
        def slugify(texto: str) -> str:
            return re.sub(r"[^a-zA-Z0-9]+", "_", texto).strip("_").lower()

        def matriz_seleccionable(ctx: str, factor_id: str, factor_label: str, niveles: list, default=2) -> int:
            state_key = f"nivel_{ctx}_{factor_id}"

            if state_key not in st.session_state:
                st.session_state[state_key] = int(default)

            seleccionado = int(st.session_state[state_key])

            st.markdown(f'<div class="factor-title">{factor_label}</div>', unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns(4)
            cols = [c1, c2, c3, c4]

            def _set_nivel(sk: str, val: int):
                st.session_state[sk] = int(val)

            for i in range(4):
                n = i + 1
                resumen = niveles[i]["resumen"]
                completo = niveles[i]["completo"]

                with cols[i]:
                    if seleccionado == n:
                        color = {1: "#8B2E2E", 2: "#B08900", 3: "#1F4E79", 4: "#2E7D32"}[n]
                        etiqueta_nivel = {1: "Nivel 1", 2: "Nivel 2", 3: "Nivel 3", 4: "Nivel 4"}[n]

                        st.markdown(
                            f"""
                            <div class="sel-slot">
                                <span class="sel-badge" style="border-color:{color}; color:{color};">
                                    {etiqueta_nivel}
                                </span>
                                <span style="flex:1; height:0; border-top:3px solid {color}; opacity:.9;"></span>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        st.markdown(f'<div class="cell-marker nivel-{n}"></div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="sel-slot"></div>', unsafe_allow_html=True)
                        st.markdown('<div class="cell-marker"></div>', unsafe_allow_html=True)

                    st.button(
                        resumen,
                        key=f"btn_{ctx}_{factor_id}_{n}",   # ✅ key estable por factor_id
                        help=completo,
                        use_container_width=True,
                        on_click=_set_nivel,               # ✅ evita doble click raro
                        args=(state_key, n),
                    )

            return int(st.session_state[state_key])


        # ===========================================================
        # FACTORES DE CALIDAD (UNA SOLA VEZ)
        # ===========================================================
        # ===========================================================
        # FACTORES DE CALIDAD (UNA SOLA VEZ) - ORDEN FIJO + IDS FIJOS
        # ===========================================================
        calidad = {}

        # ctx debe existir antes de usarlo en keys
        ctx = f"trab_{int(trab['id'])}"

        FACTORES_ORDEN = [
            ("conocimiento",   "CONOCIMIENTO DEL PUESTO"),
            ("criterio",       "CRITERIO"),
            ("calidad",        "CALIDAD DEL TRABAJO"),
            ("tecnica",        "TÉCNICA Y ORGANIZACIÓN DEL TRABAJO"),
            ("supervision",    "NECESIDAD DE SUPERVISIÓN"),
            ("capacitacion",   "CAPACITACIÓN RECIBIDA"),
            ("iniciativa",     "INICIATIVA"),
            ("colaboracion",   "COLABORACIÓN Y DISCRECIÓN"),
            ("responsabilidad","RESPONSABILIDAD Y DISCIPLINA"),
            ("equipo",         "TRABAJO EN EQUIPO"),
            ("relaciones",     "RELACIONES INTERPERSONALES"),
            ("mejora",         "MEJORA CONTINUA"),
        ]

        for idx, (factor_id, etiqueta) in enumerate(FACTORES_ORDEN, start=1):
            niveles = descripciones[etiqueta]

            calidad[etiqueta] = matriz_seleccionable(
                ctx=ctx,
                factor_id=factor_id,
                factor_label=f"{idx}. {etiqueta}",
                niveles=niveles,
                default=2
            )

        puntaje_total = int(sum(calidad.values()))
        st.write(f"**Puntaje total:** {puntaje_total}/48")
        st.markdown('</div>', unsafe_allow_html=True)

        # ---------------- FECHA Y COMENTARIOS ----------------
        st.subheader("Fecha y Comentarios")
        hoy = datetime.now()
        dia, mes, anio = hoy.day, hoy.month, hoy.year
        st.text_input("Fecha de Evaluación", f"{dia}/{mes}/{anio}", disabled=True)
        comentarios = st.text_area("Comentarios")
        necesidades = st.text_area("Capacitaciones necesarias")




        # ===========================================================
        # GUARDAR EVALUACIÓN EN SUPABASE
        # ===========================================================
        if st.button("Guardar Evaluación"):
            try:
                # Evitar duplicado por trabajador/mes/año
                existe = supabase.table("evaluaciones").select("id").match({
                    "trabajador_id": int(trab["id"]),
                    "mes": int(mes),
                    "anio": int(anio),
                }).execute()

                if existe.data:
                    st.error("⚠️ Ya existe una evaluación para este trabajador en este mes/año.")
                    st.stop()

                nueva_eval = {
                    "trabajador_id": int(trab["id"]),
                    "dia": int(dia),
                    "mes": int(mes),
                    "anio": int(anio),

                    "meta1_real": float(meta_real["meta1_real"]),
                    "meta2_real": float(meta_real["meta2_real"]),
                    "meta3_real": float(meta_real["meta3_real"]),

                    "resultado1": float(resultados["resultado1"]),
                    "resultado2": float(resultados["resultado2"]),
                    "resultado3": float(resultados["resultado3"]),

                    "puntaje_total": float(puntaje_total),
                    "comentarios": comentarios,
                    "necesidades_capac": necesidades,
                }

                for etiqueta, columna_sql in map_factores.items():
                    nueva_eval[columna_sql] = int(calidad[etiqueta])

                resp = supabase.table("evaluaciones").insert(nueva_eval).execute()

                if resp.data:
                    st.success(
                        f"✅ Evaluación registrada para {trab['nombre']} el {dia}/{mes}/{anio}."
                    )
                    cargar_evaluaciones_join.clear()
                else:
                    st.error("⚠️ Ocurrió un error al guardar la evaluación en Supabase.")

            except Exception as e:
                st.error(f"❌ Error al guardar en Supabase: {e}")























































