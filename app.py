import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import re
# Cerca la importació de draw_player_radar_chart i canvia-la per aquesta:
from utils.court_visualizer import draw_boxscore_zone_charts, draw_player_radar_charts
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
    get_dir_cache_key,
    load_all_raw_game_boxscores,
    get_team_logo_path 
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

st.sidebar.title("Analítica COPA CATALUNYA")

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
    "Visualitzacions", 
    ["Partits", "Acumulats Lliga", "Tirs Jugadors", "Scouting"]
)

# ----------------- VIEW 1: GAME ANALYZER -----------------
if view == "Partits":
    st.title(f"Partits ({selected_season.replace('_', ' ')})")
    
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
            # canvi: Escuts mitjans de fons a sobre de l'analitzador de partits
            st.subheader("Ràtings d'Eficiència de l'Equip")
            col_lgA, col_lgSpace, col_lgB = st.columns([4, 1, 4])
            with col_lgA:
                logo_path_t1 = get_team_logo_path(t1_name, selected_season)
                if logo_path_t1:
                    st.image(logo_path_t1, width=90)
            with col_lgB:
                logo_path_t2 = get_team_logo_path(t2_name, selected_season)
                if logo_path_t2:
                    st.image(logo_path_t2, width=90)
                    
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
elif view == "Acumulats Lliga":
    st.title(f"Acumulats Lliga ({selected_season.replace('_', ' ')})")
    
    # canvi: S'envien tant BOX_DIR com PBP_DIR per fer la cerca de Jornada en viu
    pbp_cache_key = get_dir_cache_key(BOX_DIR)
    raw_games_df = load_all_raw_game_boxscores(BOX_DIR, PBP_DIR, pbp_cache_key)
    
    if raw_games_df.empty:
        st.info("No s'han trobat dades de boxscores per calcular les tendències de la lliga.")
    else:
        # canvi: Ordenació numèrica reglamentària de les Jornades de la lliga
        week_options = sorted(
            list(raw_games_df["Week"].dropna().unique()), 
            key=lambda w: [int(s) for s in re.findall(r'\d+', w)] or [w]
        )
        
        st.subheader("Filtre dinàmic de partits de la lliga")
        
        # canvi: Interfície ultra-neta amb un Checkbox per defecte ("Totes")
        select_all_weeks = st.checkbox("Inclou Totes les Jornades de la temporada", value=True)
        
        if select_all_weeks:
            selected_weeks = week_options
            st.info("Totes les jornades estan incloses en els càlculs de lliga.")
        else:
            selected_weeks = st.multiselect(
                "Selecciona les Jornades a incloure de forma manual (desmarca per excloure'ls rànquings)",
                week_options,
                default=week_options
            )
            
        if not selected_weeks:
            st.warning("Selecciona almenys una jornada de lliga per calcular les tendències dinàmiques.")
        else:
            # Filtrem en viu els llançaments ofensius segons la Jornada triada
            filtered_raw_off = raw_games_df[raw_games_df["Week"].isin(selected_weeks)].copy()
            
            # canvi: Mètode de construcció dinàmica de dades defensives (Rival) basat en la setmana
            all_def_rows = []
            for file_name, group in raw_games_df.groupby("Game_File"):
                if len(group) == 2:
                    row0 = group.iloc[0]
                    row1 = group.iloc[1]
                    
                    # Les dades defensives de l'equip A són les dades ofensives del seu oponent (Equip B)
                    def_row0 = {
                        "Team": row0["Team"], "Game_Name": row0["Game_Name"], "Game_File": row0["Game_File"], "Week": row0["Week"],
                        "OERcal": row0["DERcal"], "DERcal": row0["OERcal"], "POSScal": row0["POSScal"],
                        "eFG%": row1["eFG%"], "TOV%cal": row1["TOV%cal"], "ORB%cal": row1["ORB%cal"], "FTR": row1["FTR"],
                        "Rim FGM": row1["Rim FGM"], "Rim FGA": row1["Rim FGA"],
                        "Paint FGM": row1["Paint FGM"], "Paint FGA": row1["Paint FGA"],
                        "MR FGM": row1["MR FGM"], "MR FGA": row1["MR FGA"],
                        "Cor3 FGM": row1["Cor3 FGM"], "Cor3 FGA": row1["Cor3 FGA"],
                        "ATB3 FGM": row1["ATB3 FGM"], "ATB3 FGA": row1["ATB3 FGA"]
                    }
                    def_row1 = {
                        "Team": row1["Team"], "Game_Name": row1["Game_Name"], "Game_File": row1["Game_File"], "Week": row1["Week"],
                        "OERcal": row1["DERcal"], "DERcal": row1["OERcal"], "POSScal": row1["POSScal"],
                        "eFG%": row0["eFG%"], "TOV%cal": row0["TOV%cal"], "ORB%cal": row0["ORB%cal"], "FTR": row0["FTR"],
                        "Rim FGM": row0["Rim FGM"], "Rim FGA": row0["Rim FGA"],
                        "Paint FGM": row0["Paint FGM"], "Paint FGA": row0["Paint FGA"],
                        "MR FGM": row0["MR FGM"], "MR FGA": row0["MR FGA"],
                        "Cor3 FGM": row0["Cor3 FGM"], "Cor3 FGA": row0["Cor3 FGA"],
                        "ATB3 FGM": row0["ATB3 FGM"], "ATB3 FGA": row0["ATB3 FGA"]
                    }
                    all_def_rows.append(def_row0)
                    all_def_rows.append(def_row1)
                    
            raw_defense_df = pd.DataFrame(all_def_rows)
            filtered_raw_def = raw_defense_df[raw_defense_df["Week"].isin(selected_weeks)].copy()
            
            # Columnes d'acumulat per promediar
            agg_cols = [
                "POSScal", "OERcal", "DERcal", "eFG%", "TOV%cal", "ORB%cal", "FTR",
                "Rim FGM", "Rim FGA", "Paint FGM", "Paint FGA", "MR FGM", "MR FGA", "Cor3 FGM", "Cor3 FGA", "ATB3 FGM", "ATB3 FGA"
            ]
            for c in agg_cols:
                if c in filtered_raw_off.columns:
                    filtered_raw_off[c] = pd.to_numeric(filtered_raw_off[c], errors="coerce").fillna(0.0)
                if c in filtered_raw_def.columns:
                    filtered_raw_def[c] = pd.to_numeric(filtered_raw_def[c], errors="coerce").fillna(0.0)
            
            # Càlcul dinàmic d'acumulats d'Atac i Defensa en temps real
            offense_df = filtered_raw_off.groupby("Team").agg({c: "mean" for c in agg_cols if c in filtered_raw_off.columns}).reset_index()
            defense_df = filtered_raw_def.groupby("Team").agg({c: "mean" for c in agg_cols if c in filtered_raw_def.columns}).reset_index()
            
            # Recalcul de percentatges de llançament per a cadascuna de les taules d'atac i defensa
            for df_t in [offense_df, defense_df]:
                for zone in ["Rim", "Paint", "MR", "Cor3", "ATB3"]:
                    fgm_c = f"{zone} FGM"
                    fga_c = f"{zone} FGA"
                    pct_c = f"{zone} %"
                    if fgm_c in df_t.columns and fga_c in df_t.columns:
                        df_t[pct_c] = (df_t[fgm_c] / df_t[fga_c] * 100.0).fillna(0.0)

            # canvi: Injectem la columna de ruta de la imatge de l'escut a cada fila
            offense_df["Escut"] = offense_df["Team"].apply(lambda t: get_team_logo_path(t, selected_season) or "")
            defense_df["Escut"] = defense_df["Team"].apply(lambda t: get_team_logo_path(t, selected_season) or "")
            
            # Re-ordenem les columnes per col·locar l'escut a l'esquerra de tot
            view_off_cols = ["Escut"] + [c for c in offense_df.columns if c != "Escut"]
            view_def_cols = ["Escut"] + [c for c in defense_df.columns if c != "Escut"]

            # canvi: Afegit el component ImageColumn per pintar els logos en petit dins la classificació
            league_col_config = {
                "Escut": st.column_config.ImageColumn("Escut", width="small"),
                "Team": st.column_config.TextColumn("Team", width=260)
            }
            for col in offense_df.columns:
                if col not in ["Team", "Escut"]:
                    league_col_config[col] = st.column_config.NumberColumn(col, width=65)

            tab_off, tab_def, tab_chart, tab_lineups = st.tabs([
                "Classificació d'Atac de la Lliga", 
                "Classificació de Defensa de la Lliga", 
                "Gràfic de Dispersió",
                "Quintets Acumulats"
            ])
            
            with tab_off:
                st.write("Classificació d'Eficiència de la Lliga (Mètriques Ofensives recalculades en viu)")
                st.dataframe(
                    offense_df[view_off_cols].sort_values("OERcal", ascending=False).style.format(precision=2), 
                    use_container_width=False, 
                    height=600,
                    column_config=league_col_config
                )
                
            with tab_def:
                st.write("Classificació d'Eficiència de la Lliga (Mètriques Defensives recalculades en viu)")
                st.dataframe(
                    defense_df[view_def_cols].sort_values("DERcal", ascending=True).style.format(precision=2), 
                    use_container_width=False, 
                    height=600,
                    column_config=league_col_config
                )
                
            with tab_chart:
                st.write("Gràfic d'Anàlisi Dinàmica de la Lliga (Exclou partits i veu els canvis en directe)")
                
                # Merge offense and defense to get complete metrics
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
                
                pbp_cache_key = get_dir_cache_key(PBP_DIR)
                
                # Carreguem dades de quintets i dades brutes de fons
                agg_lineups_all, combined_df = load_and_aggregate_season_lineups(PBP_DIR, selected_agg_team, pbp_cache_key)
                
                if combined_df.empty:
                    st.info("No s'han trobat dades de quintets per a aquest equip en els fitxers Play-by-Play d'aquesta temporada.")
                else:
                    # canvi: Sincronització de jornades dinàmica estricta (mètode de fons de la Fase 4)
                    # Formatem la setmana de combined_df en format de cerca "Jornada X"
                    combined_df["Week_Str"] = combined_df["Week"].apply(
                    lambda w: f"Jornada {int(float(w))}" if isinstance(w, (int, float)) or str(w).replace('.', '', 1).isdigit() else f"Jornada {w}"
                )
                
                # Filtrem en viu les files de rotacions brutes segons les Jornades seleccionades
                combined_df_filtered = combined_df[combined_df["Week_Str"].isin(selected_weeks)].copy()
                
                if combined_df_filtered.empty:
                    st.warning("No hi ha dades de quintets disponibles per a les jornades seleccionades.")
                else:
                    # canvi: Recalculem de manera dinàmica la taula acumulada segons el tall temporal triat
                    numeric_cols = [
                        "PTS_For", "PTS_Agn", "+/-", "FTM_For", "FTA_For", "FTM_Agn", "FTA_Agn", 
                        "FOULS_Cor", "FOULS_Dra", "TOV_For", "TOV_Agn",
                        "RO_For", "RD_For", "RO_Agn", "RD_Agn"
                    ]
                    for col in combined_df_filtered.columns:
                        col_lower = col.lower()
                        if any(z in col_lower for z in ["rim", "paint", "mr", "cor", "atb"]):
                            if any(term in col_lower for term in ["fga", "fgm", "%", "pct"]):
                                numeric_cols.append(col)
                                
                    available_numeric = [c for c in list(set(numeric_cols)) if c in combined_df_filtered.columns]
                    
                    agg_dict = {c: "sum" for c in available_numeric}
                    for c in ["P1", "P2", "P3", "P4", "P5"]:
                        if c in combined_df_filtered.columns:
                            agg_dict[c] = "first"
                            
                    agg_lineups = combined_df_filtered.groupby("Lineup").agg(agg_dict).reset_index()
                    
                    for suffix in ["_For", "_Agn"]:
                        fga_2p = f"2PA{suffix}"
                        fgm_2p = f"2PM{suffix}"
                        pct_2p = f"2P%{suffix}"
                        if fga_2p in agg_lineups.columns and fgm_2p in agg_lineups.columns:
                            agg_lineups[pct_2p] = (agg_lineups[fgm_2p] / agg_lineups[fga_2p] * 100.0).fillna(0.0)
                            
                        fga_3p = f"3PA{suffix}"
                        fgm_3p = f"3PM{suffix}"
                        pct_3p = f"3P%{suffix}"
                        if fga_3p in agg_lineups.columns and fgm_3p in agg_lineups.columns:
                            agg_lineups[pct_3p] = (agg_lineups[fgm_3p] / agg_lineups[fga_3p] * 100.0).fillna(0.0)
                            
                    if "+/-" in agg_lineups.columns:
                        agg_lineups = agg_lineups.sort_values("+/-", ascending=False)
                    
                    # Pintem el dataframe de dades dinàmic de la setmana seleccionada
                    lineup_cols = [
                        "P1", "P2", "P3", "P4", "P5", "Lineup", "PTS_For", "PTS_Agn", "+/-", 
                        "RO_For", "RD_For", "RO_Agn", "RD_Agn",
                        "2PA_For", "2P%_For", "2PA_Agn", "2P%_Agn",
                        "3PA_For", "3P%_For", "3PA_Agn", "3P%_Agn",
                        "TOV_For", "TOV_Agn"
                    ]
                    selected_lineup_cols = [c for c in lineup_cols if c in agg_lineups.columns]
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
                            
                    st.write(f"Rendiment Acumulat de Quintets de **{selected_agg_team}** (Filtre dinàmic actiu)")
                    st.dataframe(
                        agg_lineups[selected_lineup_cols], 
                        use_container_width=False,
                        column_config=lineup_col_config,
                        hide_index=True
                    )
                    
                    st.markdown("---")
                    st.subheader("Anàlisi de Coincidència i Rànquing de Parelles")
                    
                    roster = set()
                    for c in ["P1", "P2", "P3", "P4", "P5"]:
                        if c in agg_lineups.columns:
                            roster.update(agg_lineups[c].dropna().unique())
                    roster_list = sorted(list(roster))
                    
                    col_pX, col_pY = st.columns(2)
                    with col_pX:
                        player_X = st.selectbox("Selecciona el Jugador A (Principal)", roster_list, index=0)
                    with col_pY:
                        roster_with_none = ["Cap (Només Jugador A)"] + [p for p in roster_list if p != player_X]
                        player_Y = st.selectbox("Selecciona el Jugador B (Opcional)", roster_with_none, index=0)
                        
                    def calculate_combo_stats_metrics(df):
                        if df.empty:
                            return 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0
                        
                        def sum_cols_matching(patterns):
                            total = 0.0
                            for col in df.columns:
                                col_lower = col.lower()
                                if all(p in col_lower for p in patterns):
                                    total += df[col].sum()
                            return total

                        rim_fga_for = sum_cols_matching(["rim", "fga", "for"])
                        rim_fgm_for = sum_cols_matching(["rim", "fgm", "for"])
                        paint_fga_for = sum_cols_matching(["paint", "fga", "for"])
                        paint_fgm_for = sum_cols_matching(["paint", "fgm", "for"])
                        mr_fga_for = sum_cols_matching(["mr", "fga", "for"])
                        mr_fgm_for = sum_cols_matching(["mr", "fgm", "for"])
                        cor_fga_for = sum_cols_matching(["cor", "fga", "for"])
                        cor_fgm_for = sum_cols_matching(["cor", "fgm", "for"])
                        atb_fga_for = sum_cols_matching(["atb", "fga", "for"])
                        atb_fgm_for = sum_cols_matching(["atb", "fgm", "for"])
                        
                        rim_fga_agn = sum_cols_matching(["rim", "fga", "ag"])
                        rim_fgm_agn = sum_cols_matching(["rim", "fgm", "ag"])
                        paint_fga_agn = sum_cols_matching(["paint", "fga", "ag"])
                        paint_fgm_agn = sum_cols_matching(["paint", "fgm", "ag"])
                        mr_fga_agn = sum_cols_matching(["mr", "fga", "ag"])
                        mr_fgm_agn = sum_cols_matching(["mr", "fgm", "ag"])
                        cor_fga_agn = sum_cols_matching(["cor", "fga", "ag"])
                        cor_fgm_agn = sum_cols_matching(["cor", "fgm", "ag"])
                        atb_fga_agn = sum_cols_matching(["atb", "fga", "ag"])
                        atb_fgm_agn = sum_cols_matching(["atb", "fgm", "ag"])
                        
                        fga_2p_for = rim_fga_for + paint_fga_for + mr_fga_for
                        fgm_2p_for = rim_fgm_for + paint_fgm_for + mr_fgm_for
                        fga_3p_for = cor_fga_for + atb_fga_for
                        fgm_3p_for = cor_fgm_for + atb_fgm_for
                        
                        fga_for = fga_2p_for + fga_3p_for
                        fgm_for_weighted = fgm_2p_for + 1.5 * fgm_3p_for
                        
                        fga_2p_agn = rim_fga_agn + paint_fga_agn + mr_fga_agn
                        fgm_2p_agn = rim_fgm_agn + paint_fgm_agn + mr_fgm_agn
                        fga_3p_agn = cor_fga_agn + atb_fga_agn
                        fgm_3p_agn = cor_fgm_agn + atb_fgm_agn
                        
                        fga_agn = fga_2p_agn + fga_3p_agn
                        fgm_agn_weighted = fgm_2p_agn + 1.5 * fgm_3p_agn
                        
                        off_efg = (fgm_for_weighted / fga_for * 100.0) if fga_for > 0 else 0.0
                        def_efg = (fgm_agn_weighted / fga_agn * 100.0) if fga_agn > 0 else 0.0
                        
                        tov_for = sum_cols_matching(["tov", "for"])
                        fta_for = sum_cols_matching(["fta", "for"])
                        poss_for = fga_for + 0.44 * fta_for + tov_for
                        to_pct = (tov_for / poss_for * 100.0) if poss_for > 0 else 0.0
                        
                        tov_agn = sum_cols_matching(["tov", "agn"]) + sum_cols_matching(["tov", "ag"])
                        fta_agn = sum_cols_matching(["fta", "agn"]) + sum_cols_matching(["fta", "ag"])
                        poss_agn = fga_agn + 0.44 * fta_agn + tov_agn
                        to_pct_ag = (tov_agn / poss_agn * 100.0) if poss_agn > 0 else 0.0
                        
                        ro = int(sum_cols_matching(["ro", "for"]) + sum_cols_matching(["oreb", "for"]) + sum_cols_matching(["orb", "for"]))
                        rd = int(sum_cols_matching(["rd", "for"]) + sum_cols_matching(["dreb", "for"]) + sum_cols_matching(["drb", "for"]))
                        
                        ro_ag = int(sum_cols_matching(["ro", "agn"]) + sum_cols_matching(["oreb", "agn"]) + sum_cols_matching(["orb", "agn"]) + sum_cols_matching(["ro", "ag"]) + sum_cols_matching(["oreb", "ag"]) + sum_cols_matching(["orb", "ag"]))
                        rd_ag = int(sum_cols_matching(["rd", "agn"]) + sum_cols_matching(["dreb", "agn"]) + sum_cols_matching(["drb", "agn"]) + sum_cols_matching(["rd", "ag"]) + sum_cols_matching(["dreb", "ag"]) + sum_cols_matching(["drb", "ag"]))
                        
                        return off_efg, def_efg, to_pct, to_pct_ag, ro, ro_ag, rd, rd_ag

                    if player_Y == "Cap (Només Jugador A)":
                        # canvi: Càlculs estrictament lligats a les Jornades seleccionades
                        on_court = combined_df_filtered[combined_df_filtered["Lineup"].str.contains(player_X, na=False)]
                        off_court = combined_df_filtered[~combined_df_filtered["Lineup"].str.contains(player_X, na=False)]
                        
                        st.write(f"Rendiment global d'On/Off per a **{player_X}** (Filtrat per setmanes):")
                        col_on, col_off = st.columns(2)
                        with col_on:
                            plus_on = on_court["+/-"].sum() if not on_court.empty else 0.0
                            st.metric(
                                label=f"A Pista ({player_X})", 
                                value=f"{plus_on:+.1f}",
                                help=f"Equip jugant amb el Jugador A a pista. Punts a favor: {on_court['PTS_For'].sum():.0f}, Punts en contra: {on_court['PTS_Agn'].sum():.0f}"
                            )
                        with col_off:
                            plus_off = off_court["+/-"].sum() if not off_court.empty else 0.0
                            st.metric(
                                label=f"A la Banqueta (Off-Court)", 
                                value=f"{plus_off:+.1f}",
                                help=f"Equip jugant sense el Jugador A a pista. Punts a favor: {off_court['PTS_For'].sum():.0f}, Punts en contra: {off_court['PTS_Agn'].sum():.0f}"
                            )
                            
                        st.write("")
                        teammate_stats = []
                        for teammate in roster_list:
                            if teammate == player_X:
                                continue
                            
                            # canvi: El rànquing de parelles ara es calcula estrictament sobre les Jornades seleccionades (combined_df_filtered)
                            both_on_raw = combined_df_filtered[
                                combined_df_filtered["Lineup"].str.contains(player_X, na=False) & 
                                combined_df_filtered["Lineup"].str.contains(teammate, na=False)
                            ]
                            
                            if not both_on_raw.empty:
                                o_efg, d_efg, to_p, to_pa, ro, ro_ag, rd, rd_ag = calculate_combo_stats_metrics(both_on_raw)
                                
                                if "Week" in both_on_raw.columns and "Rival" in both_on_raw.columns:
                                    both_on_raw = both_on_raw.copy()
                                    both_on_raw["Game_ID"] = both_on_raw["Week"].astype(str) + "_" + both_on_raw["Rival"].astype(str)
                                    partits_junts = int(both_on_raw["Game_ID"].nunique())
                                elif "Rival" in both_on_raw.columns:
                                    partits_junts = int(both_on_raw["Rival"].nunique())
                                else:
                                    partits_junts = 1
                                    
                                trams_junts = int(len(both_on_raw))
                                
                                teammate_stats.append({
                                    "Company": teammate,
                                    "+/- Acumulat": both_on_raw["+/-"].sum(),
                                    "Partits": partits_junts,
                                    "Trams": trams_junts,
                                    "off eFG%": o_efg,
                                    "def eFG%": d_efg,
                                    "to%": to_p,
                                    "to%ag": to_pa,
                                    "ro": ro,
                                    "ro Ag": ro_ag,
                                    "rd": rd,
                                    "rd ag": rd_ag
                                })
                                
                        if teammate_stats:
                            teammate_df = pd.DataFrame(teammate_stats).sort_values("+/- Acumulat", ascending=False)
                            
                            col_best, col_worst = st.columns(2)
                            
                            t_config = {
                                "Company": st.column_config.TextColumn("Company", width=240),
                                "+/- Acumulat": st.column_config.NumberColumn("+/- Acum", width="small"),
                                "Partits": st.column_config.NumberColumn("Partits", width="small"),
                                "Trams": st.column_config.NumberColumn("Trams", width="small")
                            }
                            for col in ["off eFG%", "def eFG%", "to%", "to%ag"]:
                                t_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width="small")
                            for col in ["ro", "ro Ag", "rd", "rd ag"]:
                                t_config[col] = st.column_config.NumberColumn(col, width="small")
                                
                            with col_best:
                                st.write(f"👍 **Millors companyies per a {player_X}**")
                                st.dataframe(
                                    teammate_df.head(3), 
                                    use_container_width=False, 
                                    hide_index=True, 
                                    column_config=t_config
                                )
                            with col_best:
                                pass
                            with col_worst:
                                st.write(f"👎 **Pitjors companyies per a {player_X}**")
                                st.dataframe(
                                    teammate_df.tail(3).sort_values("+/- Acumulat", ascending=True), 
                                    use_container_width=False, 
                                    hide_index=True, 
                                    column_config=t_config
                                )
                    else:
                        # --- MODE 2: ANALISI CREUAT COMPLET (DOS JUGADORS) ---
                        # Cerca dinàmica sobre el segment triat de la temporada (combined_df_filtered)
                        both_on = combined_df_filtered[combined_df_filtered["Lineup"].str.contains(player_X, na=False) & combined_df_filtered["Lineup"].str.contains(player_Y, na=False)]
                        only_X = combined_df_filtered[combined_df_filtered["Lineup"].str.contains(player_X, na=False) & ~combined_df_filtered["Lineup"].str.contains(player_Y, na=False)]
                        only_Y = combined_df_filtered[~combined_df_filtered["Lineup"].str.contains(player_X, na=False) & combined_df_filtered["Lineup"].str.contains(player_Y, na=False)]
                        both_off = combined_df_filtered[~combined_df_filtered["Lineup"].str.contains(player_X, na=False) & ~combined_df_filtered["Lineup"].str.contains(player_Y, na=False)]
                        
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
elif view == "Tirs Jugadors":
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
        
        for col in ["Rim FGA", "Paint FGA", "MR FGA", "Cor3 FGA", "ATB3 FGA", "Rim %", "Paint %", "MR %", "Cor3 %", "ATB3 %"]:
            if col in master_players.columns:
                master_players[col] = pd.to_numeric(master_players[col], errors='coerce').fillna(0.0)
        
        # Parse TIME column to float minutes for numerical filtering
        master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
        
        st.write("Motor de cerca acumulats dels jugadors de la temporada. Els percentatges indiquen l'**Eficiència de Tir**, mentre que el **FGA** indica el volum total d'intents.")
        
        # canvi: Afegit filtre d'Equip obligatori per a la llista d'índex de tir
        st.subheader("Filtres de la Taula")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            player_teams = ["Tots els equips"] + sorted(list(master_players["Team"].dropna().unique()))
            selected_player_team = st.selectbox("Filtra per Equip", player_teams)
        with col_t2:
            sort_metric_sel = st.selectbox("Criteri de Classificació Principal", ["eFG% (Eficiència)", "Punts", "Partits Jugats", "FGA (Volum)", "Minuts per Partit"])
            
        col_filt1, col_filt2, col_filt3 = st.columns(3)
        with col_filt1:
            min_games = st.slider("Mínim de partits jugats", 1, int(master_players["GamesPlayed"].max() or 20), 5)
        with col_filt2:
            min_fga = st.slider("Mínim de FGA per partit (Volum)", 0.0, float(master_players["FGA"].max() or 20.0), 2.0, step=0.5)
        with col_filt3:
            min_mins = st.slider("Mínim de minuts per partit (Presència)", 0.0, float(master_players["MinPerGame"].max() or 40.0), 10.0, step=1.0)
            
        # Apliquem el filtre d'equip i de volum creuat
        filtered_players = master_players.copy()
        if selected_player_team != "Tots els equips":
            filtered_players = filtered_players[filtered_players["Team"] == selected_player_team]
            
        filtered_players = filtered_players[
            (filtered_players["GamesPlayed"] >= min_games) &
            (filtered_players["FGA"] >= min_fga) &
            (filtered_players["MinPerGame"] >= min_mins)
        ]
        
        if filtered_players.empty:
            st.info("No hi ha jugadors que compleixin els filtres seleccionats.")
        else:
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
            
            # canvi: MÒDUL DE DOBLE RÀDAR EN PARAL·LEL (VOLUM VS EFICIÈNCIA AMB INTEGRACIÓ DE MOSTRES)
            st.markdown("---")
            st.subheader("📊 Ràdars de Tir Comparatius del Jugador")
            st.write("Analitza el perfil del jugador: el gràfic de l'esquerra mostra on llança (Volum) i el de la dreta mostra quant encerta (Eficiència), especificant el número total de tirs fets als eixos.")
            
            players_radar_list = sorted(list(filtered_players["JUGADOR"].unique()))
            selected_radar_player = st.selectbox("Selecciona un jugador per veure el seu ràdar de tir", players_radar_list)
            
            player_row = filtered_players[filtered_players["JUGADOR"] == selected_radar_player].iloc[0]
            
            # Càlcul de mètriques de la lliga (mitjana d'intents i de percentatges sobre llançadors reals)
            league_averages = {
                "Rim_FGA": master_players["Rim FGA"].mean() or 0.0,
                "Paint_FGA": master_players["Paint FGA"].mean() or 0.0,
                "MR_FGA": master_players["MR FGA"].mean() or 0.0,
                "Cor3_FGA": master_players["Cor3 FGA"].mean() or 0.0,
                "ATB3_FGA": master_players["ATB3 FGA"].mean() or 0.0,
                "Rim_Pct": master_players[master_players["Rim FGA"] > 0]["Rim %"].mean() or 0.0,
                "Paint_Pct": master_players[master_players["Paint FGA"] > 0]["Paint %"].mean() or 0.0,
                "MR_Pct": master_players[master_players["MR FGA"] > 0]["MR %"].mean() or 0.0,
                "Cor3_Pct": master_players[master_players["Cor3 FGA"] > 0]["Cor3 %"].mean() or 0.0,
                "ATB3_Pct": master_players[master_players["ATB3 FGA"] > 0]["ATB3 %"].mean() or 0.0
            }
            
            # Calculem el rang de de volum màxim per a l'escala
            league_max_fga = {
                "Rim": master_players["Rim FGA"].max() or 1.0,
                "Paint": master_players["Paint FGA"].max() or 1.0,
                "MR": master_players["MR FGA"].max() or 1.0,
                "Cor3": master_players["Cor3 FGA"].max() or 1.0,
                "ATB3": master_players["ATB3 FGA"].max() or 1.0
            }
            
            # Generem el doble ràdar programàtic lliure d'errors
            fig_vol_rad, fig_eff_rad = draw_player_radar_charts(player_row, league_averages, league_max_fga)
            
            col_rad1, col_map2 = st.columns(2)
            with col_rad1:
                st.plotly_chart(fig_vol_rad, use_container_width=True)
            with col_map2:
                st.plotly_chart(fig_eff_rad, use_container_width=True)
            # canvi: Nova taula resum compacta en píxels sota els ràdars comparant Tirs, PPS i vs. Lliga en viu
            zones_list = ["Rim", "Paint", "MR", "Cor3", "ATB3"]
            zone_names_cat = {
                "Rim": "A prop del cercle (Rim)",
                "Paint": "Pintura (Paint)",
                "MR": "Mitjana distància (MR)",
                "Cor3": "Triple cantonada (Corner 3)",
                "ATB3": "Triple frontal (ATB3)"
            }
             # canvi: Definim games_played directament a app.py per resoldre la referència de Pylance
            games_played = max(1.0, float(player_row.get("GamesPlayed", 1.0)))
            table_rows = []
            for zone in zones_list:
                is_3pt = zone in ["Cor3", "ATB3"]
                multiplier = 3.0 if is_3pt else 2.0
                
                # Càlculs de dades del jugador
                fga = float(player_row.get(f"{zone} FGA", 0.0))
                pct = float(player_row.get(f"{zone} %", 0.0))
                total_shots = int(round(fga * games_played))
                player_pps = multiplier * (pct / 100.0)
                
                # Càlculs de dades de la mitjana de lliga
                league_pct = float(league_averages.get(f"{zone}_Pct", 0.0))
                league_pps = multiplier * (league_pct / 100.0)
                
                # Diferència net de rendiment (PPS)
                diff_pps = player_pps - league_pps
                
                table_rows.append({
                    "Zona": zone_names_cat[zone],
                    "Tirs Totals": total_shots,
                    "Punts per Tir (PPS)": player_pps,
                    "vs. Mitjana de la Lliga": diff_pps
                })
                
            radar_table_df = pd.DataFrame(table_rows)
            
            # Disseny compacte unificat de píxels
            radar_table_config = {
                "Zona": st.column_config.TextColumn("Zona", width=240),
                "Tirs Totals": st.column_config.NumberColumn("Tirs Totals", width="small"),
                "Punts per Tir (PPS)": st.column_config.NumberColumn("Punts per Tir (PPS)", format="%.2f", width="small"),
                "vs. Mitjana de la Lliga": st.column_config.NumberColumn("vs. Mitjana de la Lliga", format="%+.2f", width="medium")
            }
            
            st.write(f"Resum de dades de tir detallades per zones de **{player_row['JUGADOR']}**:")
            st.dataframe(
                radar_table_df,
                use_container_width=False,
                column_config=radar_table_config,
                hide_index=True
            )

# ----------------- VIEW 4: SCOUTING DE RIVALS -----------------
elif view == "Scouting":
    st.title(f"Scouting ({selected_season.replace('_', ' ')})")
    
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
            # canvi: Capçalera amb escuts grans cara a cara a l'Scouting de Rivals
            col_logo_A, col_vs, col_logo_B = st.columns([1, 0.5, 1])
            with col_logo_A:
                logo_path_A = get_team_logo_path(team_A, selected_season)
                if logo_path_A:
                    st.image(logo_path_A, width=140)
                else:
                    st.subheader(team_A)
            with col_vs:
                # Centrem el text VS respecte a l'alçada dels escuts
                st.markdown("<h2 style='text-align: center; line-height: 140px; color: gray;'>VS</h2>", unsafe_allow_html=True)
            with col_logo_B:
                logo_path_B = get_team_logo_path(team_B, selected_season)
                if logo_path_B:
                    st.image(logo_path_B, width=140)
                else:
                    st.subheader(team_B)
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