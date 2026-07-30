import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

from utils.data_loader import (
    get_available_seasons, 
    load_all_game_options, 
    parse_boxscore, 
    parse_pbp, 
    parse_aggregate,
    resolve_path_case_insensitive,
    get_total_team_minutes,
    estimate_game_duration,
    find_best_matching_pbp,
    normalize_and_format_player_times,
    parse_time_to_minutes
)
from utils.court_visualizer import draw_colorblind_shot_charts

# Page config & Theme (Must be first)
st.set_page_config(page_title="Anàlisi de Bàsquet - Staff", layout="wide")

# Control d'Accés de Seguretat (Login)
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.title("🔒 Accés per a l'Staff")
        correct_password = st.secrets.get("auth", {}).get("password", None)
        
        if not correct_password:
            st.error("Les contrasenyes d'accés no estan configurades. Contacta amb l'administrador.")
            st.stop()
            
        entered_password = st.text_input("Introdueix la contrasenya de l'Staff", type="password")
        if st.button("Inicia Sessió"):
            if entered_password == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Contrasenya incorrecta.")
        st.stop()

check_password()

# --- Rest of the application ---

RAW_DIR = "data/raw"

CB_BLUE = "#1f77b4"
CB_ORANGE = "#ff7f0e"
CB_NEUTRAL = "#4a4a4a"

st.sidebar.title("🏀 Hub de l'Staff")

# 1. Season Selector in Sidebar
seasons = get_available_seasons(RAW_DIR)

if not seasons:
    st.sidebar.error("Crea una carpeta de temporada (ex: 'Copa_2025_2026') dins de data/raw/")
    st.info("Estructura de carpetes: `data/raw/NOM_DE_LA_TEMPORADA/pbp/`, etc.")
    st.stop()

selected_season = st.sidebar.selectbox("Selecciona la Temporada", seasons)

# 2. Dynamically resolve paths case-insensitively with Root Folder Fallbacks
PBP_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "pbp")
if not PBP_DIR or not os.path.exists(PBP_DIR):
    PBP_DIR = resolve_path_case_insensitive(RAW_DIR, "pbp")

BOX_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "boxscores")
if not BOX_DIR or not os.path.exists(BOX_DIR):
    BOX_DIR = resolve_path_case_insensitive(RAW_DIR, "boxscores")

AGG_FILE = resolve_path_case_insensitive(RAW_DIR, selected_season, "aggregate", "aggregate_season_latest.xlsx")
if not AGG_FILE or not os.path.exists(AGG_FILE):
    AGG_FILE = resolve_path_case_insensitive(RAW_DIR, "aggregate", "aggregate_season_latest.xlsx")

# 3. View selector (Sidebar)
view = st.sidebar.radio("Navega per les Vistes", ["Analitzador de Partits", "Tendències de la Lliga", "Índex de Tir dels Jugadors"])

# ----------------- VIEW 1: GAME ANALYZER -----------------
if view == "Analitzador de Partits":
    st.title(f"Analitzador de Partits ({selected_season.replace('_', ' ')})")
    
    if not BOX_DIR or not os.path.exists(BOX_DIR):
        st.info("No s'ha trobat la carpeta de boxscores. Comprova els noms de directori.")
    else:
        games = load_all_game_options(BOX_DIR)
        
        if not games:
            st.info("No s'han carregat partits. Afegeix els teus fitxers de boxscore/pbp de la setmana.")
        else:
            selected_game = st.selectbox("Selecciona el Partit", games, format_func=lambda g: g["name"])
            
            # Parse data
            team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])
            
            # Robust team name overlay matching for PBP sheets
            pbp_path = find_best_matching_pbp(t1_name, t2_name, PBP_DIR, selected_game["filename"])
            has_pbp = pbp_path is not None and os.path.exists(pbp_path)
            
            pbp_df_param = None
            if has_pbp:
                pbp_df, shot_zone_df, lineups_df = parse_pbp(pbp_path)
                pbp_df_param = pbp_df
            
            # Calculate standard regulation/OT game duration (player times are left unscaled/pristine)
            estimated_game_mins = estimate_game_duration(t1_players, t2_players, pbp_df_param)
            
            # --- Subsection 1: Advanced Metrics (OER/DER/PACE) ---
            st.subheader("Ràtings d'Eficiència de l'Equip")
            col1, col2, col3, col4 = st.columns(4)
            
            t1_stats = team_summary.iloc[0]
            t2_stats = team_summary.iloc[1]
            
            with col1:
                st.metric(label="Possessions (Ritme/Pace)", value=f"{t1_stats['POSScal']:.1f}")
            with col2:
                st.metric(label=f"Ràting d'Atac / Defensa - {t1_name}", value=f"{t1_stats['OERcal']:.1f} / {t1_stats['DERcal']:.1f}")
            with col3:
                st.metric(label=f"Ràting d'Atac / Defensa - {t2_name}", value=f"{t2_stats['OERcal']:.1f} / {t2_stats['DERcal']:.1f}")
            with col4:
                st.metric(
                    label="Durada del Partit", 
                    value=f"{estimated_game_mins} min", 
                    help=f"Durada estàndard estimada del partit (Reglamentari o Pròrrogues)."
                )
                
            # --- Subsection 2: Four Factors Comparison ---
            st.subheader("Comparació dels 4 Factors")
            factors = ["eFG%", "TOV%cal", "ORB%cal", "FTR"]
            
            col_f1, col_f2 = st.columns(2)
            for i, factor in enumerate(factors):
                target_col = col_f1 if i % 2 == 0 else col_f2
                with target_col:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        y=[t1_name, t2_name],
                        x=[t1_stats[factor], t2_stats[factor]],
                        orientation='h',
                        marker_color=[CB_BLUE, CB_ORANGE],
                        text=[f"{t1_stats[factor]:.2f}", f"{t2_stats[factor]:.2f}"],
                        textposition='inside'
                    ))
                    fig.update_layout(
                        title=f"Factor: {factor}",
                        height=200,
                        margin=dict(l=20, r=20, t=40, b=20),
                        plot_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=False)
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # --- Subsection 3: Dynamic Boxscores View ---
            st.markdown("---")
            st.subheader("Perfils de Rendiment dels Jugadors")
            
            # View Selector for Boxscores to prevent page horizontal scroll
            stat_view = st.radio(
                "Selecciona la vista d'estadístiques", 
                ["Estadístiques Estàndard", "Mètriques Avançades", "Sèries per Zona de Tir"], 
                horizontal=True
            )
            
            # Standard columns groupings
            standard_cols = ["JUGADOR", "TIME", "PTS", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA", "ORB", "DRB", "AS", "STL", "BLK", "TO", "F", "F+"]
            advanced_cols = ["JUGADOR", "TIME", "EFI", "USG%cal", "eFG%", "TS%", "FTR", "TO%cal", "PTS/PLAYcal", "TOpts", "2CPts"]
            zone_cols = ["JUGADOR", "TIME", "Rim FGM", "Rim FGA", "Rim %", "Paint FGM", "Paint FGA", "Paint %", "MR FGM", "MR FGA", "MR %", "Cor3 FGM", "Cor3 FGA", "Cor3 %", "ATB3 FGM", "ATB3 FGA", "ATB3 %"]

            team_tab1, team_tab2 = st.tabs([t1_name, t2_name])
            
            for tab, players_df in zip([team_tab1, team_tab2], [t1_players, t2_players]):
                with tab:
                    # Filter columns dynamically based on selection and file headers
                    if stat_view == "Estadístiques Estàndard":
                        selected_cols = [c for c in standard_cols if c in players_df.columns]
                    elif stat_view == "Mètriques Avançades":
                        selected_cols = [c for c in advanced_cols if c in players_df.columns]
                    else:
                        selected_cols = [c for c in zone_cols if c in players_df.columns]
                        
                    st.dataframe(players_df[selected_cols].style.format(precision=2), use_container_width=True)
                
            # --- Subsection 4: PBP-Specific Tabs ---
            if has_pbp:
                st.markdown("---")
                st.subheader("Flux de Joc i Quintets")
                pbp_tab, lineup_tab = st.tabs(["Gràfics de Tir i Registre de Jugades", "Quintets Actius"])
                
                with pbp_tab:
                    # Filter translations
                    all_players_list = ["Tots"] + sorted(list(pbp_df["Player"].dropna().unique()))
                    shot_player_sel = st.selectbox("Filtra els llançaments per jugador", all_players_list)
                    shot_player = "All" if shot_player_sel == "Tots" else shot_player_sel
                    
                    # Renders side-by-side shot charts for Volume & PPS (Blocked Proportions)
                    fig_vol, fig_pps = draw_colorblind_shot_charts(pbp_df, selected_player=shot_player)
                    
                    col_map1, col_map2 = st.columns(2)
                    with col_map1:
                        st.plotly_chart(fig_vol, use_container_width=True)
                    with col_map2:
                        st.plotly_chart(fig_pps, use_container_width=True)
                        
                    st.markdown("---")
                    st.write("Registre de Jugades (Registre de Temps)")
                    st.dataframe(pbp_df[["quarter", "time", "text"]].dropna().head(100), height=500, use_container_width=True)
                    
                with lineup_tab:
                    st.write("Rendiment dels Quintets a la Pista")
                    st.dataframe(lineups_df, use_container_width=True)
            else:
                st.warning("No s'ha trobat cap fitxer Play-By-Play per a aquest partit. S'ha fet una cerca aproximada però no hi ha coincidències.")

# ----------------- VIEW 2: LEAGUE & SEASON TRENDS -----------------
elif view == "Tendències de la Lliga":
    st.title(f"Tendències de la Lliga ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No s'ha trobat el fitxer d'acumulats de lliga. Afegeix 'aggregate_season_latest.xlsx' a la seva carpeta.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        tab_off, tab_def, tab_chart = st.tabs(["Classificació d'Atac de la Lliga", "Classificació de Defensa de la Lliga", "Gràfic de Dispersió"])
        
        with tab_off:
            st.write("Classificació d'Eficiència de la Lliga (Mètriques Ofensives)")
            st.dataframe(offense_df.sort_values("OERcal", ascending=False).style.format(precision=2), use_container_width=True, height=600)
            
        with tab_def:
            st.write("Classificació d'Eficiència de la Lliga (Mètriques Defensives)")
            st.dataframe(defense_df.sort_values("DERcal", ascending=True).style.format(precision=2), use_container_width=True, height=600)
            
        with tab_chart:
            st.write("Gràfic d'Anàlisi Dinàmica de la Lliga")
            
            # Merge offense and defense to get complete metrics
            league_df = offense_df.merge(defense_df, on="Team", suffixes=("_Off", "_Def"))
            
            # Dictionary maps parsed cleanly to avoid inline multi-line lambda compile warnings
            x_labels = {
                "OERcal_Off": "Ràting Ofensiu (OER)",
                "eFG%_Off": "eFG% Ofensiu",
                "TOV%cal_Off": "Ràtio de Pèrdues Ofensiu (TO%)",
                "ORB%cal_Off": "Rebot Ofensiu % (ORB%)",
                "FTR_Off": "Ràtio de Tirs Lliures Ofensiu (FTR)"
            }
            
            y_labels = {
                "DERcal_Off": "Ràting Defensiu (DER)",
                "eFG%_Def": "eFG% Defensiu (Rival eFG%)",
                "TOV%cal_Def": "Ràtio de Pèrdues Defensiu (Rival TO%)",
                "ORB%cal_Def": "Rebot Ofensiu Rival % (Rival ORB%)",
                "FTR_Def": "Ràtio de Tirs Lliures Defensiu (Rival FTR)"
            }
            
            # Let the coaches select which metric to plot on X and Y
            col_scat1, col_scat2 = st.columns(2)
            with col_scat1:
                x_metric = st.selectbox(
                    "Eix X (Mètrica Ofensiva)", 
                    list(x_labels.keys()),
                    format_func=lambda x: x_labels[x]
                )
            with col_scat2:
                y_metric = st.selectbox(
                    "Eix Y (Mètrica Defensiva)", 
                    list(y_labels.keys()),
                    format_func=lambda y: y_labels[y]
                )
            
            fig_scat = px.scatter(
                league_df,
                x=x_metric,
                y=y_metric,
                hover_name="Team",
                title="Gràfic de Dispersió Comparatiu de la Lliga",
                labels={
                    "OERcal_Off": "Ràting Ofensiu (OER)",
                    "DERcal_Off": "Ràting Defensiu (DER)",
                    "eFG%_Off": "eFG% Ofensiu",
                    "eFG%_Def": "eFG% Rival",
                    "TOV%cal_Off": "TO% Ofensiu",
                    "TOV%cal_Def": "TO% Rival",
                    "ORB%cal_Off": "Rebot Ofensiu %",
                    "ORB%cal_Def": "Rebot Ofensiu Rival %",
                    "FTR_Off": "FTR",
                    "FTR_Def": "FTR Defensiu"
                },
                color_discrete_sequence=[CB_BLUE]
            )
            
            # Add dynamic average lines
            mean_x = league_df[x_metric].mean()
            mean_y = league_df[y_metric].mean()
            fig_scat.add_vline(x=mean_x, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Atac")
            fig_scat.add_hline(y=mean_y, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Def")
            
            # Reverse Y axis only if it is DER, Def eFG%, or Def FTR (where lower value is better)
            if y_metric in ["DERcal_Off", "eFG%_Def", "FTR_Def"]:
                fig_scat.update_yaxes(autorange="reversed")
                
            st.plotly_chart(fig_scat, use_container_width=True)

# ----------------- VIEW 3: PLAYER SHOOTING INDEX -----------------
elif view == "Índex de Tir dels Jugadors":
    st.title(f"Índex de Tir dels Jugadors ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No s'han trobat acumulats de lliga. Comprova els fitxers d'acumulats de la temporada.")
    else:
        _, _, master_players = parse_aggregate(AGG_FILE)
        
        # Clean numeric profiles
        master_players["GamesPlayed"] = pd.to_numeric(master_players["GamesPlayed"], errors='coerce')
        master_players["PTS"] = pd.to_numeric(master_players["PTS"], errors='coerce')
        master_players["eFG%"] = pd.to_numeric(master_players["eFG%"], errors='coerce')
        master_players["FGA"] = pd.to_numeric(master_players["FGA"], errors='coerce')
        
        # Parse TIME column to float minutes for numerical filtering
        master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
        
        st.write("Motor de cerca de tirs acumulats per jugador de la temporada. Filtra per nivell de volum.")
        
        # Leaderboard Filters
        st.subheader("Filtres de la Taula")
        col_filt1, col_filt2, col_filt3 = st.columns(3)
        with col_filt1:
            min_games = st.slider("Mínim de partits jugats", 1, int(master_players["GamesPlayed"].max() or 20), 5)
        with col_filt2:
            min_fga = st.slider("Mínim de FGA per partit", 0.0, float(master_players["FGA"].max() or 20.0), 2.0, step=0.5)
        with col_filt3:
            min_mins = st.slider("Mínim de minuts per partit", 0.0, float(master_players["MinPerGame"].max() or 40.0), 10.0, step=1.0)
            
        filtered_players = master_players[
            (master_players["GamesPlayed"] >= min_games) &
            (master_players["FGA"] >= min_fga) &
            (master_players["MinPerGame"] >= min_mins)
        ]
        
        sort_metric_sel = st.selectbox("Criteri de Classificació Principal", ["eFG%", "Punts", "Partits Jugats", "FGA", "Minuts per Partit"])
        
        sort_metric_mapping = {
            "eFG%": "eFG%",
            "Punts": "PTS",
            "Partits Jugats": "GamesPlayed",
            "FGA": "FGA",
            "Minuts per Partit": "MinPerGame"
        }
        sort_metric = sort_metric_mapping[sort_metric_sel]
        
        sorted_players = filtered_players.sort_values(sort_metric, ascending=False)
        
        # Display clean structured dataframe
        view_cols = ["JUGADOR", "Team", "GamesPlayed", "TIME", "FGA", "PTS", "eFG%", "TS%", "Rim %", "Paint %", "MR %", "Cor3 %", "ATB3 %"]
        
        st.dataframe(
            sorted_players[view_cols].style.format({
                "TIME": "{}", # Time is already formatted clean string
                "FGA": "{:.1f}",
                "PTS": "{:.1f}",
                "eFG%": "{:.2f}%",
                "TS%": "{:.2f}%",
                "Rim %": "{:.1f}%",
                "Paint %": "{:.1f}%",
                "MR %": "{:.1f}%",
                "Cor3 %": "{:.1f}%",
                "ATB3 %": "{:.1f}%"
            }),
            use_container_width=True
        )