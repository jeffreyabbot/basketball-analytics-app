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
    parse_time_to_minutes,
    tag_shot_team,
    load_and_aggregate_season_lineups,
    get_dir_cache_key
)
from utils.court_visualizer import draw_boxscore_zone_charts

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
view = st.sidebar.radio(
    "Navega per les Vistes", 
    ["Analitzador de Partits", "Tendències de la Lliga", "Índex de Tir dels Jugadors", "Scouting de Rivals"]
)

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
            # canvi: Mètode definitiu utilitzant els noms de la lliga com a origen per filtrar els partits
            if os.path.exists(AGG_FILE):
                offense_df, _, _ = parse_aggregate(AGG_FILE)
                teams_list = sorted(list(offense_df["Team"].unique()))
            else:
                # Fallback de seguretat si no es troba l'aggregate
                all_game_teams = set()
                for g in games:
                    if " vs " in g["name"]:
                        parts = g["name"].split(" vs ")
                        all_game_teams.add(parts[0].strip())
                        all_game_teams.add(parts[1].strip())
                teams_list = sorted(list(all_game_teams))
            
            filter_team_game = st.selectbox("1. Filtra els partits per equip", teams_list)
            
            # Filtrem strictly els partits d'aquest equip seleccionat
            filtered_games = [g for g in games if filter_team_game.lower() in g["name"].lower()]
                
            selected_game = st.selectbox("2. Selecciona el Partit", filtered_games, format_func=lambda g: g["name"])
            
            # Parse data
            team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])
            
            # Robust team name overlay matching for PBP sheets
            pbp_path = find_best_matching_pbp(t1_name, t2_name, PBP_DIR, selected_game["filename"])
            has_pbp = pbp_path is not None and os.path.exists(pbp_path)
            
            pbp_df_param = None
            if has_pbp:
                pbp_df, shot_zone_df, lineups_df = parse_pbp(pbp_path)
                pbp_df = tag_shot_team(pbp_df, t1_name, t2_name)
                pbp_df_param = pbp_df
            
            # Calculate standard regulation/OT game duration
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
                    help="Durada d'aquest partit basada en els períodes jugats."
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
                        xaxis=dict(showgrid=False, range=[0.0, 80.0] if factor != "FTR" else [0.0, 0.80])
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # --- Subsection 3: Dynamic Boxscores View ---
            st.markdown("---")
            st.subheader("Perfils de Rendiment dels Jugadors")
            
            stat_view = st.radio(
                "Selecciona la vista d'estadístiques", 
                ["Estadístiques Estàndard", "Mètriques Avançades", "Sèries per Zona de Tir"], 
                horizontal=True
            )
            
            standard_cols = ["JUGADOR", "TIME", "PTS", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA", "ORB", "DRB", "AS", "STL", "BLK", "TO", "F", "F+"]
            advanced_cols = ["JUGADOR", "TIME", "EFI", "USG%cal", "eFG%", "TS%", "FTR", "TO%cal", "PTS/PLAYcal", "TOpts", "2CPts"]
            zone_cols = ["JUGADOR", "TIME", "Rim FGM", "Rim FGA", "Rim %", "Paint FGM", "Paint FGA", "Paint %", "MR FGM", "MR FGA", "MR %", "Cor3 FGM", "Cor3 FGA", "Cor3 %", "ATB3 FGM", "ATB3 FGA", "ATB3 %"]

            team_tab1, team_tab2 = st.tabs([t1_name, t2_name])
            
            for tab, players_df in zip([team_tab1, team_tab2], [t1_players, t2_players]):
                with tab:
                    if stat_view == "Estadístiques Estàndard":
                        selected_cols = [c for c in standard_cols if c in players_df.columns]
                    elif stat_view == "Mètriques Avançades":
                        selected_cols = [c for c in advanced_cols if c in players_df.columns]
                    else:
                        selected_cols = [c for c in zone_cols if c in players_df.columns]
                        
                    col_config = {
                        "JUGADOR": st.column_config.TextColumn("JUGADOR", width=260)
                    }
                    for col in selected_cols:
                        if col != "JUGADOR":
                            if col == "TIME":
                                col_config[col] = st.column_config.TextColumn(col, width=65)
                            else:
                                col_config[col] = st.column_config.NumberColumn(col, width=55)
                                
                    st.dataframe(
                        players_df[selected_cols].style.format(precision=2), 
                        use_container_width=False,
                        column_config=col_config
                    )
                
            # --- Subsection 4: PBP-Specific Tabs ---
            if has_pbp:
                st.markdown("---")
                st.subheader("Flux de Joc i Quintets")
                pbp_tab, lineup_tab = st.tabs(["Gràfics de Tir i Registre de Jugades", "Quintets Actius"])
                
                with pbp_tab:
                    col_sel1, col_sel2 = st.columns(2)
                    with col_sel1:
                        selected_team = st.selectbox("Filtra per Equip", ["Tots els equips", t1_name, t2_name])
                    with col_sel2:
                        if selected_team == "Tots els equips":
                            players_list = sorted(list(pbp_df["Player"].dropna().unique()))
                        else:
                            players_list = sorted(list(pbp_df[pbp_df["Shot_Team"] == selected_team]["Player"].dropna().unique()))
                        
                        all_players_list = ["Tots"] + players_list
                        shot_player_sel = st.selectbox("Filtra els llançaments per jugador", all_players_list)
                        shot_player = "All" if shot_player_sel == "Tots" else shot_player_sel
                    
                    pbp_df_filtered = pbp_df.copy()
                    if selected_team != "Tots els equips":
                        pbp_df_filtered = pbp_df_filtered[pbp_df_filtered["Shot_Team"] == selected_team]
                        
                    fig_vol, fig_pps = draw_boxscore_zone_charts(
                        team_summary=team_summary,
                        t1_players=t1_players,
                        t2_players=t2_players,
                        t1_name=t1_name,
                        t2_name=t2_name,
                        selected_team=selected_team,
                        selected_player=shot_player
                    )
                    
                    col_map1, col_map2 = st.columns(2)
                    with col_map1:
                        st.plotly_chart(fig_vol, use_container_width=True)
                    with col_map2:
                        st.plotly_chart(fig_pps, use_container_width=True)
                        
                    st.markdown("---")
                    st.write("Registre de Jugades (Registre de Temps)")
                    st.dataframe(pbp_df[["quarter", "time", "text"]].dropna().head(100), height=500, use_container_width=True)
                    
                with lineup_tab:
                    # Filtre d'equip obligatori per a la taula de quintets (lineups)
                    selected_lineup_team = st.selectbox("Filtra els quintets per equip", ["Tots els equips", t1_name, t2_name])
                    filtered_lineups = lineups_df.copy()
                    
                    if selected_lineup_team != "Tots els equips":
                        team_col = None
                        for col in lineups_df.columns:
                            if lineups_df[col].astype(str).str.contains(t1_name, na=False).any() or lineups_df[col].astype(str).str.contains(t2_name, na=False).any():
                                team_col = col
                                break
                        if team_col is not None:
                            filtered_lineups = filtered_lineups[filtered_lineups[team_col] == selected_lineup_team]
                    
                    # Neteja de canvis i eliminació de dades redundants de quintets de la lliga
                    cols_to_drop = []
                    for col in filtered_lineups.columns:
                        col_lower = str(col).lower()
                        if any(term in col_lower for term in ["tounf", "stl", "blk", "ast"]):
                            cols_to_drop.append(col)
                        elif any(zone in col_lower for zone in ["rim", "paint", "mr", "cor3", "atb3"]) and "fgm" in col_lower:
                            cols_to_drop.append(col)
                            
                    filtered_lineups = filtered_lineups.drop(columns=cols_to_drop, errors="ignore")
                    
                    pct_cols = [c for c in filtered_lineups.columns if "%" in str(c) or "pct" in str(c).lower()]
                    for col in pct_cols:
                        filtered_lineups[col] = pd.to_numeric(filtered_lineups[col], errors="coerce").fillna(0.0)
                        if filtered_lineups[col].max() <= 1.0:
                            filtered_lineups[col] = filtered_lineups[col] * 100.0
                    
                    # Mapeig dinàmic d'amplades i format de percentatge corregit per a quintets
                    lineup_col_config = {}
                    for col in filtered_lineups.columns:
                        col_str = str(col).strip()
                        
                        if col_str in ["P1", "P2", "P3", "P4", "P5"]:
                            lineup_col_config[col] = st.column_config.TextColumn(col, width="medium")
                        elif col_str == "Lineup":
                            lineup_col_config[col] = st.column_config.TextColumn(col, width="large")
                        elif col_str in pct_cols:
                            lineup_col_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width="small")
                        elif pd.api.types.is_numeric_dtype(filtered_lineups[col]):
                            lineup_col_config[col] = st.column_config.NumberColumn(col, width="small")
                        else:
                            lineup_col_config[col] = st.column_config.TextColumn(col, width="small")
                            
                    st.write("Rendiment dels Quintets a la Pista")
                    st.dataframe(
                        filtered_lineups, 
                        use_container_width=False,
                        column_config=lineup_col_config
                    )
            else:
                st.warning("No s'ha trobat cap fitxer Play-By-Play per a aquest partit. S'ha fet una cerca aproximada però no hi ha coincidències.")

# ----------------- VIEW 2: LEAGUE & SEASON TRENDS -----------------
elif view == "Tendències de la Lliga":
    st.title(f"Tendències de la Lliga ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No s'ha trobat el fitxer d'acumulats de lliga. Afegeix 'aggregate_season_latest.xlsx' a la seva carpeta.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        # Configuració de columnes compacta en píxels per a les taules de lliga (sense estirament)
        league_col_config = {
            "Team": st.column_config.TextColumn("Team", width=260)
        }
        for col in offense_df.columns:
            if col != "Team":
                league_col_config[col] = st.column_config.NumberColumn(col, width=65)

        # canvi: Afegida la quarta pestanya per a l'acumulador de quintets multipartit de la Fase 3
        tab_off, tab_def, tab_chart, tab_lineups = st.tabs([
            "Classificació d'Atac de la Lliga", 
            "Classificació de Defensa de la Lliga", 
            "Gràfic de Dispersió",
            "Quintets Acumulats"
        ])
        
        with tab_off:
            st.write("Classificació d'Eficiència de la Lliga (Mètriques Ofensives)")
            st.dataframe(
                offense_df.sort_values("OERcal", ascending=False).style.format(precision=2), 
                use_container_width=False, 
                height=600,
                column_config=league_col_config
            )
            
        with tab_def:
            st.write("Classificació d'Eficiència de la Lliga (Mètriques Defensives)")
            st.dataframe(
                defense_df.sort_values("DERcal", ascending=True).style.format(precision=2), 
                use_container_width=False, 
                height=600,
                column_config=league_col_config
            )
            
        with tab_chart:
            st.write("Gràfic d'Anàlisi Dinàmica de la Lliga")
            
            league_df = offense_df.merge(defense_df, on="Team", suffixes=("_Off", "_Def"))
            
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
                
            mean_x = league_df[x_metric].mean()
            mean_y = league_df[y_metric].mean()
            
            max_dev_x = max(abs(league_df[x_metric] - mean_x))
            max_dev_y = max(abs(league_df[y_metric] - mean_y))
            
            x_range = [mean_x - max_dev_x * 1.15, mean_x + max_dev_x * 1.15]
            
            if y_metric in ["DERcal_Off", "eFG%_Def", "FTR_Def"]:
                y_range = [mean_y + max_dev_y * 1.15, mean_y - max_dev_y * 1.15]
            else:
                y_range = [mean_y - max_dev_y * 1.15, mean_y + max_dev_y * 1.15]
            
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
            
            fig_scat.update_layout(
                height=650,
                xaxis=dict(range=x_range),
                yaxis=dict(range=y_range)
            )
            
            fig_scat.add_vline(x=mean_x, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Atac")
            fig_scat.add_hline(y=mean_y, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Def")
                
            st.plotly_chart(fig_scat, use_container_width=True)
            
        with tab_lineups:
            scout_teams = sorted(list(offense_df["Team"].unique()))
            selected_agg_team = st.selectbox("Selecciona l'Equip per analitzar els seus Quintets acumulats", scout_teams)
            
            # canvi: Invalidació intel·ligent de memòria cau basada en temps de modificació
            pbp_cache_key = get_dir_cache_key(PBP_DIR)
            
            # Carreguem els quintets de lliga de manera instantània des de la cache
            agg_lineups = load_and_aggregate_season_lineups(PBP_DIR, selected_agg_team, pbp_cache_key)
            
            if agg_lineups.empty:
                st.info("No s'han trobat dades de quintets per a aquest equip en els fitxers Play-by-Play d'aquesta temporada.")
            else:
                # Columnes configurades incloent rebots (RO/RD), volums i % de 2P i 3P (Team i Rival)
                lineup_cols = [
                    "P1", "P2", "P3", "P4", "P5", "Lineup", "PTS_For", "PTS_Agn", "+/-", 
                    "RO_For", "RD_For", "RO_Agn", "RD_Agn",
                    "2PA_For", "2P%_For", "2PA_Agn", "2P%_Agn",
                    "3PA_For", "3P%_For", "3PA_Agn", "3P%_Agn",
                    "TOV_For", "TOV_Agn"
                ]
                selected_lineup_cols = [c for c in lineup_cols if c in agg_lineups.columns]
                
                # Formatadors compactes de percentatges
                pct_cols = [c for c in selected_lineup_cols if "%" in c]
                
                lineup_col_config = {}
                for col in selected_lineup_cols:
                    if col in ["P1", "P2", "P3", "P4", "P5"]:
                        lineup_col_config[col] = st.column_config.TextColumn(col, width="medium")
                    elif col == "Lineup":
                        lineup_col_config[col] = st.column_config.TextColumn(col, width="large")
                    elif col in pct_cols:
                        lineup_col_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width="small")
                    else:
                        lineup_col_config[col] = st.column_config.NumberColumn(col, width="small")
                        
                st.write(f"Rendiment Acumulat dels Quintets de **{selected_agg_team}** (Temporada Completa)")
                st.dataframe(
                    agg_lineups[selected_lineup_cols], 
                    use_container_width=False,
                    column_config=lineup_col_config,
                    hide_index=True
                )
                
                # canvi: ANALITZADOR CREUAT DE COMBINACIONS DE JUGADORS (On Court vs Off Court)
                st.markdown("---")
                st.subheader("Anàlisi Creuat de Parelles de Jugadors (Coincidència a Pista)")
                
                # Extraiem la llista de jugadors únics del roster de l'equip
                roster = set()
                for c in ["P1", "P2", "P3", "P4", "P5"]:
                    if c in agg_lineups.columns:
                        roster.update(agg_lineups[c].dropna().unique())
                roster_list = sorted(list(roster))
                
                col_pX, col_pY = st.columns(2)
                with col_pX:
                    player_X = st.selectbox("Selecciona el Jugador X", roster_list, index=0)
                with col_pY:
                    player_Y = st.selectbox("Selecciona el Jugador Y", roster_list, index=min(1, len(roster_list)-1))
                    
                if player_X == player_Y:
                    st.warning("Selecciona dos jugadors diferents per poder calcular la coincidència creuada.")
                else:
                    # Divisió matemàtica estricta dels quintets temporals en els 4 estats possibles
                    both_on = agg_lineups[agg_lineups["Lineup"].str.contains(player_X, na=False) & agg_lineups["Lineup"].str.contains(player_Y, na=False)]
                    only_X = agg_lineups[agg_lineups["Lineup"].str.contains(player_X, na=False) & ~agg_lineups["Lineup"].str.contains(player_Y, na=False)]
                    only_Y = agg_lineups[~agg_lineups["Lineup"].str.contains(player_X, na=False) & agg_lineups["Lineup"].str.contains(player_Y, na=False)]
                    both_off = agg_lineups[~agg_lineups["Lineup"].str.contains(player_X, na=False) & ~agg_lineups["Lineup"].str.contains(player_Y, na=False)]
                    
                    st.write(f"Rendiment de l'equip segons la presència de **{player_X}** i **{player_Y}**:")
                    
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    
                    with col_m1:
                        plus_minus = both_on["+/-"].sum() if not both_on.empty else 0.0
                        st.metric(
                            label="Junts a Pista", 
                            value=f"{plus_minus:+.1f}",
                            help=f"Ambdós jugadors jugant junts. Punts a favor: {both_on['PTS_For'].sum():.0f}, Punts en contra: {both_on['PTS_Agn'].sum():.0f}"
                        )
                    with col_m2:
                        plus_minus = only_X["+/-"].sum() if not only_X.empty else 0.0
                        st.metric(
                            label=f"Només {player_X}", 
                            value=f"{plus_minus:+.1f}",
                            help=f"Jugador X jugant sense Jugador Y. Punts a favor: {only_X['PTS_For'].sum():.0f}, Punts en contra: {only_X['PTS_Agn'].sum():.0f}"
                        )
                    with col_m3:
                        plus_minus = only_Y["+/-"].sum() if not only_Y.empty else 0.0
                        st.metric(
                            label=f"Només {player_Y}", 
                            value=f"{plus_minus:+.1f}",
                            help=f"Jugador Y jugant sense Jugador X. Punts a favor: {only_Y['PTS_For'].sum():.0f}, Punts en contra: {only_Y['PTS_Agn'].sum():.0f}"
                        )
                    with col_m4:
                        plus_minus = both_off["+/-"].sum() if not both_off.empty else 0.0
                        st.metric(
                            label="Ambdós a la Banqueta", 
                            value=f"{plus_minus:+.1f}",
                            help=f"Cap dels dos jugadors a pista. Punts a favor: {both_off['PTS_For'].sum():.0f}, Punts en contra: {both_off['PTS_Agn'].sum():.0f}"
                        )

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
        
        for col in ["Rim FGA", "Paint FGA", "MR FGA", "Cor3 FGA", "ATB3 FGA"]:
            if col in master_players.columns:
                master_players[col] = pd.to_numeric(master_players[col], errors='coerce').fillna(0.0)
        
        # Parse TIME column to float minutes for numerical filtering
        master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
        
        st.write("Motor de cerca acumulats dels jugadors de la temporada. Els percentatges indiquen l'**Eficiència de Tir**, mentre que el **FGA** indica el volum total d'intents.")
        
        # Leaderboard Filters
        st.subheader("Filtres de la Taula")
        col_filt1, col_filt2, col_filt3 = st.columns(3)
        with col_filt1:
            min_games = st.slider("Mínim de partits jugats", 1, int(master_players["GamesPlayed"].max() or 20), 5)
        with col_filt2:
            min_fga = st.slider("Mínim de FGA per partit (Volum)", 0.0, float(master_players["FGA"].max() or 20.0), 2.0, step=0.5)
        with col_filt3:
            min_mins = st.slider("Mínim de minuts per partit (Presència)", 0.0, float(master_players["MinPerGame"].max() or 40.0), 10.0, step=1.0)
            
        filtered_players = master_players[
            (master_players["GamesPlayed"] >= min_games) &
            (master_players["FGA"] >= min_fga) &
            (master_players["MinPerGame"] >= min_mins)
        ]
        
        sort_metric_sel = st.selectbox("Criteri de Classificació Principal", ["eFG% (Eficiència)", "Punts", "Partits Jugats", "FGA (Volum)", "Minuts per Partit"])
        
        sort_metric_mapping = {
            "eFG% (Eficiència)": "eFG%",
            "Punts": "PTS",
            "Partits Jugats": "GamesPlayed",
            "FGA (Volum)": "FGA",
            "Minuts per Partit": "MinPerGame"
        }
        sort_metric = sort_metric_mapping[sort_metric_sel]
        
        sorted_players = filtered_players.sort_values(sort_metric, ascending=False)
        
        view_cols = [
            "JUGADOR", "Team", "GamesPlayed", "TIME", "FGA", "PTS", "eFG%", 
            "Rim FGA", "Rim %", "Paint FGA", "Paint %", "MR FGA", "MR %", "Cor3 FGA", "Cor3 %", "ATB3 FGA", "ATB3 %"
        ]
        
        # Mètode dinàmic d'autoajust compacte en píxels per a l'índex de tir (sin estiramiento)
        player_index_config = {
            "JUGADOR": st.column_config.TextColumn("JUGADOR", width=260),
            "Team": st.column_config.TextColumn("Team", width=160)
        }
        for col in view_cols:
            if col not in ["JUGADOR", "Team"]:
                if col == "TIME":
                    player_index_config[col] = st.column_config.TextColumn(col, width=65)
                else:
                    player_index_config[col] = st.column_config.NumberColumn(col, width=60)
        
        st.dataframe(
            sorted_players[view_cols].style.format({
                "TIME": "{}", 
                "FGA": "{:.1f}",
                "PTS": "{:.1f}",
                "eFG%": "{:.2f}%",
                "TS%": "{:.2f}%",
                "Rim FGA": "{:.1f}",
                "Rim %": "{:.1f}%",
                "Paint FGA": "{:.1f}",
                "Paint %": "{:.1f}%",
                "MR FGA": "{:.1f}",
                "MR %": "{:.1f}%",
                "Cor3 FGA": "{:.1f}",
                "Cor3 %": "{:.1f}%",
                "ATB3 FGA": "{:.1f}",
                "ATB3 %": "{:.1f}%"
            }),
            use_container_width=False,
            column_config=player_index_config
        )

# ----------------- VIEW 4: SCOUTING DE RIVALS -----------------
elif view == "Scouting de Rivals":
    st.title(f"Mòdul de Scouting de Rivals ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No s'ha trobat el fitxer d'acumulats de lliga. Afegeix 'aggregate_season_latest.xlsx' a la seva carpeta.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        teams_list = sorted(list(offense_df["Team"].unique()))
        col_tA, col_tB = st.columns(2)
        with col_tA:
            team_A = st.selectbox("Selecciona l'Equip A", teams_list, index=0)
        with col_tB:
            team_B = st.selectbox("Selecciona l'Equip B", teams_list, index=min(1, len(teams_list)-1))
            
        if team_A == team_B:
            st.warning("Selecciona dos equips diferents per poder fer la comparativa de scouting.")
        else:
            st.markdown("---")
            st.subheader("Comparativa de Rànquings i Eficiència de l'Equip")
            
            off_ranks = offense_df.copy()
            def_ranks = defense_df.copy()
            
            # OER, eFG%, ORB%, FTR, POSScal rànquing alt és millor (descending)
            # DER, TOV% cal rànquing baix és millor (ascending)
            off_ranks["OER_Rank"] = off_ranks["OERcal"].rank(ascending=False, method="min")
            off_ranks["eFG_Rank"] = off_ranks["eFG%"].rank(ascending=False, method="min")
            off_ranks["ORB_Rank"] = off_ranks["ORB%cal"].rank(ascending=False, method="min")
            off_ranks["FTR_Rank"] = off_ranks["FTR"].rank(ascending=False, method="min")
            off_ranks["Pace_Rank"] = off_ranks["POSScal"].rank(ascending=False, method="min")
            off_ranks["TOV_Rank"] = off_ranks["TOV%cal"].rank(ascending=True, method="min")
            
            def_ranks["DER_Rank"] = def_ranks["OERcal"].rank(ascending=True, method="min")
            def_ranks["eFG_Def_Rank"] = def_ranks["eFG%"].rank(ascending=True, method="min")
            def_ranks["TOV_Def_Rank"] = def_ranks["TOV%cal"].rank(ascending=False, method="min")
            def_ranks["ORB_Def_Rank"] = def_ranks["ORB%cal"].rank(ascending=True, method="min")
            def_ranks["FTR_Def_Rank"] = def_ranks["FTR"].rank(ascending=True, method="min")
            
            def get_team_scout_stats(team_name):
                t_off = off_ranks[off_ranks["Team"] == team_name].iloc[0]
                t_def = def_ranks[def_ranks["Team"] == team_name].iloc[0]
                return {
                    "OER": (t_off["OERcal"], int(t_off["OER_Rank"])),
                    "DER": (t_def["OERcal"], int(t_def["DER_Rank"])),
                    "Pace": (t_off["POSScal"], int(t_off["Pace_Rank"])),
                    "eFG": (t_off["eFG%"], int(t_off["eFG_Rank"])),
                    "TOV": (t_off["TOV%cal"], int(t_off["TOV_Rank"])),
                    "ORB": (t_off["ORB%cal"], int(t_off["ORB_Rank"])),
                    "FTR": (t_off["FTR"], int(t_off["FTR_Rank"])),
                    "eFG_Def": (t_def["eFG%"], int(t_def["eFG_Def_Rank"])),
                    "TOV_Def": (t_def["TOV%cal"], int(t_def["TOV_Def_Rank"])),
                    "ORB_Def": (t_def["ORB%cal"], int(t_def["ORB_Def_Rank"])),
                    "FTR_Def": (t_def["FTR"], int(t_def["FTR_Def_Rank"]))
                }
                
            stats_A = get_team_scout_stats(team_A)
            stats_B = get_team_scout_stats(team_B)
            
            mirror_data = []
            metrics_mapping = [
                ("OER", "Ràting Ofensiu (OER)", "{:.2f}"),
                ("DER", "Ràting Defensiu (DER)", "{:.2f}"),
                ("Pace", "Possessions (Pace)", "{:.1f}"),
                ("eFG", "eFG% Ofensiu", "{:.2f}%"),
                ("eFG_Def", "eFG% Defensiu (Rival eFG%)", "{:.2f}%"),
                ("TOV", "Pèrdues Ofensiu % (TO%)", "{:.2f}%"),
                ("TOV_Def", "Pèrdues Defensiu % (Forçades)", "{:.2f}%"),
                ("ORB", "Rebot Ofensiu % (ORB%)", "{:.2f}%"),
                ("ORB_Def", "Rebot Defensiu % (Rival ORB%)", "{:.2f}%"),
                ("FTR", "Ràtio de Tirs Lliures Ofensiu (FTR)", "{:.2f}"),
                ("FTR_Def", "Ràtio de Tirs Lliures Defensiu (Rival FTR)", "{:.2f}")
            ]
            
            def cat_rank(num):
                if num == 1: return "1er"
                elif num == 2: return "2on"
                elif num == 3: return "3er"
                elif num == 4: return "4rt"
                else: return f"{num}è"
                
            for key, name, fmt in metrics_mapping:
                val_A, rank_A = stats_A[key]
                val_B, rank_B = stats_B[key]
                
                str_A = f"{cat_rank(rank_A)} ({fmt.format(val_A)})"
                str_B = f"{cat_rank(rank_B)} ({fmt.format(val_B)})"
                mirror_data.append({
                    f"Rànquing ({team_A})": str_A,
                    "Mètrica de Lliga": name,
                    f"Rànquing ({team_B})": str_B
                })
                
            # canvi: Convertit a st.dataframe compacte amb amplades fixes i index ocult
            mirror_df = pd.DataFrame(mirror_data)
            mirror_col_config = {
                f"Rànquing ({team_A})": st.column_config.TextColumn(f"Rànquing ({team_A})", width=220),
                "Mètrica de Lliga": st.column_config.TextColumn("Mètrica de Lliga", width=260),
                f"Rànquing ({team_B})": st.column_config.TextColumn(f"Rànquing ({team_B})", width=220)
            }
            st.dataframe(
                mirror_df,
                use_container_width=False,
                column_config=mirror_col_config,
                hide_index=True
            )
            
            st.markdown("---")
            st.subheader("Anàlisi Comparatiu de Jugadors (Volum i PPS per Trams)")
            
            def calculate_player_splits_scout(team_name):
                df_players = master_players[master_players["Team"] == team_name].copy()
                
                cols_to_parse = [
                    "Rim FGA", "Paint FGA", "MR FGA", "Rim FGM", "Paint FGM", "MR FGM", 
                    "Cor3 FGA", "ATB3 FGA", "Cor3 FGM", "ATB3 FGM", "GamesPlayed"
                ]
                for c in cols_to_parse:
                    if c in df_players.columns:
                        df_players[c] = pd.to_numeric(df_players[c], errors='coerce').fillna(0.0)
                        
                df_players["FGA_2P"] = df_players["Rim FGA"] + df_players["Paint FGA"] + df_players["MR FGA"]
                df_players["FGM_2P"] = df_players["Rim FGM"] + df_players["Paint FGM"] + df_players["MR FGM"]
                df_players["PPS_2P"] = (2.0 * df_players["FGM_2P"]) / df_players["FGA_2P"]
                df_players["PPS_2P"] = df_players["PPS_2P"].fillna(0.0)
                
                df_players["FGA_3P"] = df_players["Cor3 FGA"] + df_players["ATB3 FGA"]
                df_players["FGM_3P"] = df_players["Cor3 FGM"] + df_players["ATB3 FGM"]
                df_players["PPS_3P"] = (3.0 * df_players["FGM_3P"]) / df_players["FGA_3P"]
                df_players["PPS_3P"] = df_players["PPS_3P"].fillna(0.0)
                
                scout_cols = ["JUGADOR", "GamesPlayed", "FGA_2P", "PPS_2P", "FGA_3P", "PPS_3P"]
                return df_players[scout_cols].sort_values("FGA_2P", ascending=False)
                
            players_A_scout = calculate_player_splits_scout(team_A)
            players_B_scout = calculate_player_splits_scout(team_B)
            
            scout_tab1, scout_tab2 = st.tabs([f"Jugadors - {team_A}", f"Jugadors - {team_B}"])
            
            scout_col_config = {
                "JUGADOR": st.column_config.TextColumn("JUGADOR", width=260)
            }
            for col in players_A_scout.columns:
                if col != "JUGADOR":
                    scout_col_config[col] = st.column_config.NumberColumn(col, width=65)

            scout_format = {
                "FGA_2P": "{:.1f}",
                "PPS_2P": "{:.2f}",
                "FGA_3P": "{:.1f}",
                "PPS_3P": "{:.2f}"
            }
            
            with scout_tab1:
                st.write(f"Volum de tirs i PPS per a llançaments de 2 i 3 punts de {team_A}")
                st.dataframe(
                    players_A_scout.style.format(scout_format), 
                    use_container_width=False, 
                    column_config=scout_col_config
                )
                
            with scout_tab2:
                st.write(f"Volum de tirs i PPS per a llançaments de 2 i 3 punts de {team_B}")
                st.dataframe(
                    players_B_scout.style.format(scout_format), 
                    use_container_width=False, 
                    column_config=scout_col_config
                )