import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import re
import glob
import base64
import unicodedata
import textwrap

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
    get_dir_cache_key,
    load_and_aggregate_season_lineups,
    load_all_raw_game_boxscores,
    calculate_combo_stats_metrics,
    get_team_logo_path,
    get_team_logo_base64_url,
    load_all_league_players_on_off 
)
from utils.court_visualizer import draw_boxscore_zone_charts, draw_player_radar_charts, draw_team_seasonal_zone_charts, draw_scouting_4f_radar_chart

# Page config & Theme (Must be first)
st.set_page_config(page_title="Anàlisi de Bàsquet - Staff", layout="wide")

# Control d'Accés de Seguretat (Login)
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.title("🔒 Dashboard Copa Catalunya - Accés Staff")
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

# Helpers de format de logos a fons en base64 per evitar deformacions
def get_logo_html_centered(logo_path, max_height=80, max_width=120):
    if not logo_path or not os.path.exists(logo_path):
        return ""
    try:
        with open(logo_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        ext = os.path.splitext(logo_path)[1].lower().replace(".", "")
        if ext not in ["png", "jpg", "jpeg"]:
            ext = "png"
        return f'''
        <div style="display: flex; justify-content: center; align-items: center; height: {max_height}px; width: 100%;">
            <img src="data:image/{ext};base64,{encoded_string}" style="max-height: {max_height}px; max-width: {max_width}px; object-fit: contain;">
        </div>
        '''
    except Exception:
        return ""

def cat_rank(num):
    if num == 1: return "1er"
    elif num == 2: return "2on"
    elif num == 3: return "3er"
    elif num == 4: return "4rt"
    else: return f"{num}è"

# Normalitza noms traient dorsals i accents per garantir encreuaments exactes
def clean_player_name_for_matching(name):
    s = str(name).strip()
    s = re.sub(r'^#\d+\s*', '', s)
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
    return s.strip().lower()

def extract_player_number(name):
    match = re.search(r'#(\d+)', str(name))
    return f"#{match.group(1)}" if match else ""

def calculate_league_average_pps(raw_games_df):
    if raw_games_df.empty:
        return 0.95
    try:
        fga_cols = ["Rim FGA", "Paint FGA", "MR FGA", "Cor3 FGA", "ATB3 FGA"]
        total_attempts = sum(raw_games_df[col].sum() for col in fga_cols if col in raw_games_df.columns)
        
        twos_cols = ["Rim FGM", "Paint FGM", "MR FGM"]
        threes_cols = ["Cor3 FGM", "ATB3 FGM"]
        
        total_2pm = sum(raw_games_df[col].sum() for col in twos_cols if col in raw_games_df.columns)
        total_3pm = sum(raw_games_df[col].sum() for col in threes_cols if col in raw_games_df.columns)
        
        total_points = 2.0 * total_2pm + 3.0 * total_3pm
        
        if total_attempts > 0:
            return total_points / total_attempts
        return 0.95
    except Exception:
        return 0.95

def highlight_offense_outliers(column):
    if not pd.api.types.is_numeric_dtype(column) or column.name in ["Team", "Escut", "Week"]:
        return [''] * len(column)
        
    mean = column.mean()
    std = column.std()
    if pd.isna(std) or std == 0:
        return [''] * len(column)
        
    lower_is_better = column.name in ["DERcal", "TOV%cal"]
    
    styles = []
    for val in column:
        if pd.isna(val):
            styles.append('')
        elif val > mean + 0.8 * std:
            if lower_is_better:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
            else:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
        elif val < mean - 0.8 * std:
            if lower_is_better:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
            else:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
        else:
            styles.append('')
    return styles

def highlight_defense_outliers(column):
    if not pd.api.types.is_numeric_dtype(column) or column.name in ["Team", "Escut", "Week"]:
        return [''] * len(column)
        
    mean = column.mean()
    std = column.std()
    if pd.isna(std) or std == 0:
        return [''] * len(column)
        
    lower_is_better = column.name in ["OERcal", "eFG%", "ORB%cal", "FTR"]
    
    styles = []
    for val in column:
        if pd.isna(val):
            styles.append('')
        elif val > mean + 0.8 * std:
            if lower_is_better:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
            else:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
        elif val < mean - 1.2 * std:
            if lower_is_better:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
            else:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
        else:
            styles.append('')
    return styles

def highlight_teammate_outliers(column):
    if column.name not in ["off eFG%", "def eFG%", "to%", "to%ag"]:
        return [''] * len(column)
        
    mean = column.mean()
    std = column.std()
    if pd.isna(std) or std == 0:
        return [''] * len(column)
        
    lower_is_better = column.name in ["def eFG%", "to%"]
    
    styles = []
    for val in column:
        if pd.isna(val):
            styles.append('')
        elif val > mean + 0.8 * std:
            if lower_is_better:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
            else:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
        elif val < mean - 0.8 * std:
            if lower_is_better:
                styles.append('background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;')
            else:
                styles.append('background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;')
        else:
            styles.append('')
    return styles

def calculate_all_players_on_off_profiles(combined_df, roster_list):
    rows = []
    for player in roster_list:
        on_court = combined_df[combined_df["Lineup"].str.contains(player, na=False)]
        off_court = combined_df[~combined_df["Lineup"].str.contains(player, na=False)]
        
        if on_court.empty or off_court.empty:
            continue
            
        o_efg_on, d_efg_on, to_on, to_ag_on, _, _, _, _ = calculate_combo_stats_metrics(on_court)
        o_efg_off, d_efg_off, to_off, to_ag_off, _, _, _, _ = calculate_combo_stats_metrics(off_court)
        
        rows.append({
            "JUGADOR": player,
            "On_eFG_Off": o_efg_on,
            "Off_eFG_Off": o_efg_off,
            "Net_eFG_Off": o_efg_on - o_efg_off,
            
            "On_eFG_Def": d_efg_on,
            "Off_eFG_Def": d_efg_off,
            "Net_eFG_Def": d_efg_on - d_efg_off,
            
            "On_TO_Off": to_on,
            "Off_TO_Off": to_off,
            "Net_TO_Off": to_on - to_off,
            
            "On_TO_Def": to_ag_on,
            "Off_TO_Def": to_ag_off,
            "Net_TO_Def": to_ag_on - to_ag_off
        })
        
    return pd.DataFrame(rows)

# Criteri d'ordenació cronològica per jornada/data de partits
def get_game_chronological_sort_key(g):
    fname = g.get("filename", "") or g.get("name", "")
    # Cerca de patrons com J1, J01, Jornada 1, Week 1
    m = re.search(r'(?:jornada|week|round|j)[\s_]*0*(\d+)', fname, re.IGNORECASE)
    if m:
        return (0, int(m.group(1)))
    m_date = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', fname)
    if m_date:
        return (1, m_date.group(0))
    digits = re.findall(r'\d+', fname)
    if digits:
        return (2, [int(d) for d in digits])
    return (3, fname)

# Carrega i extreu l'històric de partits de tots els jugadors ordenats cronològicament
@st.cache_data(show_spinner=False)
# Carrega i extreu l'històric de partits ordenats per la jornada real
@st.cache_data(show_spinner=False)
def load_all_season_player_gamelogs(box_dir, pbp_dir, cache_key):
    if not box_dir or not os.path.exists(box_dir):
        return pd.DataFrame()
        
    # Enllacem la jornada oficial de cada partit des de raw_games_df
    raw_games_df = load_all_raw_game_boxscores(box_dir, pbp_dir, cache_key)
    file_to_week = {}
    if not raw_games_df.empty and "Game_File" in raw_games_df.columns and "Week" in raw_games_df.columns:
        file_to_week = dict(zip(raw_games_df["Game_File"], raw_games_df["Week"]))
        
    games = load_all_game_options(box_dir)
    records = []
    
    # Evita duplicar punts si el boxscore conté una fila "TOTAL"
    def get_clean_team_pts(df_p):
        if df_p is None or df_p.empty or "PTS" not in df_p.columns:
            return 0
        # Excloem les files de sistema ('Faltes d'equip', 'Total') i sumem només els jugadors reals
        is_meta = df_p["JUGADOR"].astype(str).str.upper().str.contains("TOTAL|EQUIP|FALTE|TEAM")
        pts = pd.to_numeric(df_p.loc[~is_meta, "PTS"], errors="coerce").fillna(0).sum()
        if pts > 0:
            return int(round(pts))
        return int(round(pd.to_numeric(df_p["PTS"], errors="coerce").fillna(0).max()))

    for g in games:
        fname = g.get("filename", "") or g.get("name", "")
        
        # Extreiem la jornada oficial
        week_str = file_to_week.get(fname, "") or file_to_week.get(g.get("name", ""), "")
        m_j = re.search(r'\d+', str(week_str))
        if not m_j:
            m_j = re.search(r'(?:jornada|week|round|j)[\s_]*0*(\d+)', fname, re.IGNORECASE)
            
        round_num = int(m_j.group(0)) if m_j else 999
        round_label = f"J{round_num}" if round_num != 999 else ""
        
        try:
            _, (t1_name, t1_p), (t2_name, t2_p) = parse_boxscore(g["path"])
            
            score_t1 = get_clean_team_pts(t1_p)
            score_t2 = get_clean_team_pts(t2_p)
            
            for df_p, t_name, opp_name, my_sc, opp_sc in [
                (t1_p, t1_name, t2_name, score_t1, score_t2),
                (t2_p, t2_name, t1_name, score_t2, score_t1)
            ]:
                if df_p is not None and not df_p.empty and "JUGADOR" in df_p.columns:
                    w_l = "W" if my_sc >= opp_sc else "L"
                    res_text = f"{my_sc}-{opp_sc} {w_l}"
                    
                    # Filtrem la fila "TOTAL" perquè no compti com a jugador
                    p_rows = df_p[~df_p["JUGADOR"].astype(str).str.upper().str.contains("TOTAL|EQUIP|TEAM")]
                    for _, r in p_rows.iterrows():
                        p_raw = str(r["JUGADOR"]).strip()
                        records.append({
                            "JUGADOR": p_raw,
                            "Clean_Name": clean_player_name_for_matching(p_raw),
                            "Team": t_name,
                            "Opponent": opp_name,
                            "Game_Name": g["name"],
                            "Filename": fname,
                            "Round_Num": round_num,
                            "Round_Str": round_label,
                            "Score_Result": res_text,
                            "PTS": float(r.get("PTS", 0.0)),
                            "EFI": float(r.get("EFI", 0.0)),
                            "TIME": str(r.get("TIME", "00:00")),
                            "2PM": float(r.get("2PM", 0.0)),
                            "2PA": float(r.get("2PA", 0.0)),
                            "3PM": float(r.get("3PM", 0.0)),
                            "3PA": float(r.get("3PA", 0.0)),
                            "FTM": float(r.get("FTM", 0.0)),
                            "FTA": float(r.get("FTA", 0.0))
                        })
        except Exception:
            continue
            
    return pd.DataFrame(records)

RAW_DIR = "data/raw"

CB_BLUE = "#1f77b4"
CB_ORANGE = "#ff7f0e"
CB_NEUTRAL = "#4a4a4a"

copa_logo_path = "copa_catalunya.png"
if os.path.exists(copa_logo_path):
    with open(copa_logo_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode()
    
    st.sidebar.markdown(
        f'''
        <div style="display: flex; justify-content: center; align-items: center; margin-top: 15px; margin-bottom: 25px; width: 100%;">
            <img src="data:image/png;base64,{encoded_string}" style="max-height: 90px; max-width: 190px; object-fit: contain; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
        </div>
        ''', 
        unsafe_allow_html=True
    )
else:
    st.sidebar.title("Dashboard Copa Catalunya")

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
    ["Anàlisi Partits", "Acumulats Lliga", "Scouting Jugadors", "Scouting Equips"]
)

with st.sidebar.container(key="sidebar_bottom"):
    st.markdown(
        '''
        <div style="font-size: 0.75rem; color: rgba(128, 128, 128, 0.55); text-align: left; line-height: 1.4; font-family: sans-serif;">
            Dades FCBQ<br>
            Víctor Solanes 2026
        </div>
        ''', 
        unsafe_allow_html=True
    )

st.sidebar.markdown(
    """
    <style>
    div[data-element-idx="sidebar_bottom"] {
        position: absolute;
        bottom: 20px;
    }
    .st-key-sidebar_bottom {
        position: absolute;
        bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ----------------- VIEW 1: PARTITS -----------------
if view == "Anàlisi Partits":
    st.title(f"Analitzador de Partits ({selected_season.replace('_', ' ')})")
    
    if not BOX_DIR or not os.path.exists(BOX_DIR):
        st.info("No s'ha trobat la carpeta de boxscores. Comprova els noms de directori.")
    else:
        games = load_all_game_options(BOX_DIR)
        
        if not games:
            st.info("No s'han carregat partits. Afegeix els teus fitxers de boxscore/pbp de la setmana.")
        else:
            if os.path.exists(AGG_FILE):
                offense_df, _, _ = parse_aggregate(AGG_FILE)
                teams_list = sorted(list(offense_df["Team"].unique()))
            else:
                all_game_teams = set()
                for g in games:
                    if " vs " in g["name"]:
                        parts = g["name"].split(" vs ")
                        all_game_teams.add(parts[0].strip())
                        all_game_teams.add(parts[1].strip())
                teams_list = sorted(list(all_game_teams))
            
            filter_team_game = st.selectbox("1. Filtra els partits per equip", teams_list)
            filtered_games = [g for g in games if filter_team_game.lower() in g["name"].lower()]
                
            selected_game = st.selectbox("2. Selecciona el Partit", filtered_games, format_func=lambda g: g["name"])
            
            team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])
            
            pbp_path = find_best_matching_pbp(t1_name, t2_name, PBP_DIR, selected_game["filename"])
            has_pbp = pbp_path is not None and os.path.exists(pbp_path)
            
            pbp_df_param = None
            if has_pbp:
                pbp_df, shot_zone_df, lineups_df = parse_pbp(pbp_path)
                pbp_df = tag_shot_team(pbp_df, t1_name, t2_name)
                pbp_df_param = pbp_df
            
            estimated_game_mins = estimate_game_duration(t1_players, t2_players, pbp_df_param)
            
            st.subheader("Ràtings d'Eficiència de l'Equip")
            
            col_lgA, col_lgSpace, col_lgB = st.columns([4, 1, 4])
            with col_lgA:
                logo_path_t1 = get_team_logo_path(t1_name, selected_season)
                if logo_path_t1:
                    st.markdown(get_logo_html_centered(logo_path_t1, max_height=80, max_width=120), unsafe_allow_html=True)
            with col_lgB:
                logo_path_t2 = get_team_logo_path(t2_name, selected_season)
                if logo_path_t2:
                    st.markdown(get_logo_html_centered(logo_path_t2, max_height=80, max_width=120), unsafe_allow_html=True)
                    
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
                
            st.subheader("Comparació dels 4 Factors")
            factors = ["eFG%", "TOV%cal", "ORB%cal", "FTR"]
            
            factor_ranges = {
                "eFG%": [0.0, 80.0],
                "TOV%cal": [0.0, 40.0],
                "ORB%cal": [0.0, 60.0],
                "FTR": [0.0, 0.80]
            }
            
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
                        xaxis=dict(showgrid=False, range=factor_ranges[factor])
                    )
                    st.plotly_chart(fig, use_container_width=True)

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
                        
                    pbp_cache_key = get_dir_cache_key(BOX_DIR)
                    raw_games_boxscores = load_all_raw_game_boxscores(BOX_DIR, PBP_DIR, pbp_cache_key)
                    league_pps_val = calculate_league_average_pps(raw_games_boxscores)

                    fig_vol, fig_pps = draw_boxscore_zone_charts(
                        team_summary=team_summary,
                        t1_players=t1_players,
                        t2_players=t2_players,
                        t1_name=t1_name,
                        t2_name=t2_name,
                        selected_team=selected_team,
                        selected_player=shot_player,
                        league_pps=league_pps_val
                    )
                    
                    col_map1, col_map2 = st.columns(2)
                    with col_map1:
                        st.plotly_chart(fig_vol, use_container_width=True)
                    with col_map2:
                        st.plotly_chart(fig_pps, use_container_width=True)
                        
                    st.markdown("---")
                    st.write("Quarter/Time Event Feed")
                    st.dataframe(pbp_df[["quarter", "time", "text"]].dropna().head(100), height=500, use_container_width=True)
                    
                with lineup_tab:
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
                        column_config=lineup_col_config,
                        hide_index=True
                    )
            else:
                st.warning("No s'ha trobat cap fitxer Play-By-Play per a aquest partit. S'ha fet una cerca aproximada però no hi ha coincidències.")

# ----------------- VIEW 2: ACUMULATS LLIGA -----------------
elif view == "Acumulats Lliga":
    st.title(f"Tendències de la Lliga ({selected_season.replace('_', ' ')})")
    
    pbp_cache_key = get_dir_cache_key(BOX_DIR)
    raw_games_df = load_all_raw_game_boxscores(BOX_DIR, PBP_DIR, pbp_cache_key)
    
    if raw_games_df.empty:
        st.info("No s'han trobat dades de boxscores per calcular les tendències de la lliga.")
    else:
        st.subheader("Filtre dinàmic de partits de la lliga")
        
        missing_week_games = raw_games_df[raw_games_df["Week"] == "Altres / Sense Jornada"]
        if not missing_week_games.empty:
            st.warning("⚠️ S'han trobat partits que no s'han pogut assignar a cap jornada. Revisa el desplegable inferior d'avisos.")
            with st.expander("Avisos de fitxers (Alguns partits de la carpeta no tenen la Jornada assignada)"):
                st.write("Els següents partits no han trobat el seu fitxer Play-By-Play corresponent o no s'ha pogut extreure la jornada, pel que s'han assignat a 'Altres / Sense Jornada':")
                st.dataframe(
                    missing_week_games[["Game_Name", "Game_File"]].drop_duplicates(), 
                    use_container_width=True, 
                    hide_index=True
                )
                
        select_all_weeks = st.checkbox("Inclou Totes les Jornades de la temporada", value=True)
        
        week_options = sorted(
            list(raw_games_df["Week"].dropna().unique()), 
            key=lambda w: [int(s) for s in re.findall(r'\d+', w)] or [w]
        )
        
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
            filtered_raw_off = raw_games_df[raw_games_df["Week"].isin(selected_weeks)].copy()
            
            all_def_rows = []
            for file_name, group in raw_games_df.groupby("Game_File"):
                if len(group) == 2:
                    row0 = group.iloc[0]
                    row1 = group.iloc[1]
                    
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
            
            agg_cols = [
                "POSScal", "OERcal", "DERcal", "eFG%", "TOV%cal", "ORB%cal", "FTR",
                "Rim FGM", "Rim FGA", "Paint FGM", "Paint FGA", "MR FGM", "MR FGA", "Cor3 FGM", "Cor3 FGA", "ATB3 FGM", "ATB3 FGA"
            ]
            for c in agg_cols:
                if c in filtered_raw_off.columns:
                    filtered_raw_off[c] = pd.to_numeric(filtered_raw_off[c], errors="coerce").fillna(0.0)
                if c in filtered_raw_def.columns:
                    filtered_raw_def[c] = pd.to_numeric(filtered_raw_def[c], errors="coerce").fillna(0.0)
            
            offense_df = filtered_raw_off.groupby("Team").agg({c: "mean" for c in agg_cols if c in filtered_raw_off.columns}).reset_index()
            defense_df = filtered_raw_def.groupby("Team").agg({c: "mean" for c in agg_cols if c in filtered_raw_def.columns}).reset_index()
            
            for df_t in [offense_df, defense_df]:
                for zone in ["Rim", "Paint", "MR", "Cor3", "ATB3"]:
                    fgm_c = f"{zone} FGM"
                    fga_c = f"{zone} FGA"
                    pct_c = f"{zone} %"
                    if fgm_c in df_t.columns and fga_c in df_t.columns:
                        df_t[pct_c] = (df_t[fgm_c] / df_t[fga_c] * 100.0).fillna(0.0)

            offense_df["Escut"] = offense_df["Team"].apply(lambda t: get_team_logo_base64_url(t, selected_season))
            defense_df["Escut"] = defense_df["Team"].apply(lambda t: get_team_logo_base64_url(t, selected_season))
            
            view_off_cols = ["Escut"] + [c for c in offense_df.columns if c != "Escut"]
            view_def_cols = ["Escut"] + [c for c in defense_df.columns if c != "Escut"]

            league_col_config = {
                "Escut": st.column_config.ImageColumn("Escut", width="small"),
                "Team": st.column_config.TextColumn("Team", width=260)
            }
            for col in offense_df.columns:
                if col not in ["Team", "Escut"]:
                    league_col_config[col] = st.column_config.NumberColumn(col, width=65)

            tab_off, tab_def, tab_chart, tab_team_profile = st.tabs([
                "Dades Equips", 
                "Dades Rivals", 
                "Gràfic de Dispersió",
                "Perfil de Tir de l'Equip"
            ])
            
            with tab_off:
                st.write("Mètriques Ofensives dels Equips recalculades en viu (Dades Equips)")
                styled_offense = offense_df[view_off_cols].sort_values("OERcal", ascending=False).style.format(precision=2).apply(highlight_offense_outliers)
                st.dataframe(
                    styled_offense, 
                    use_container_width=False, 
                    height=600,
                    column_config=league_col_config
                )
                
            with tab_def:
                st.write("Mètriques Defensives dels Rivals recalculades en viu (Dades Rivals)")
                styled_defense = defense_df[view_def_cols].sort_values("DERcal", ascending=True).style.format(precision=2).apply(highlight_defense_outliers)
                st.dataframe(
                    styled_defense, 
                    use_container_width=False, 
                    height=600,
                    column_config=league_col_config
                )
                
            with tab_chart:
                st.write("Gràfic d'Anàlisi Dinàmica de la Lliga (Exclou partits, destaca rivals i veu els canvis en directe)")
                
                league_df = offense_df.merge(defense_df, on="Team", suffixes=("_Off", "_Def"))
                
                st.write("### Opcions de personalització del gràfic")
                teams_list_scat = sorted(list(league_df["Team"].unique()))
                
                highlight_sel = st.multiselect(
                    "Selecciona un o varis equips per destacar al gràfic (es pintaran en taronja i es faran més grans)",
                    teams_list_scat,
                    default=[]
                )
                
                def get_scat_visual_profile(row):
                    if row["Team"] in highlight_sel:
                        return "Destacat", 16
                    else:
                        return "Resta de la Lliga", 10
                        
                if highlight_sel:
                    league_df[["Visual_Group", "Visual_Size"]] = league_df.apply(
                        lambda r: pd.Series(get_scat_visual_profile(r)), axis=1
                    )
                    color_map = {
                        "Destacat": CB_ORANGE,
                        "Resta de la Lliga": "rgba(180, 180, 180, 0.55)"
                    }
                else:
                    league_df["Visual_Group"] = "Equips de la Lliga"
                    league_df["Visual_Size"] = 12
                    color_map = {
                        "Equips de la Lliga": CB_BLUE
                    }
                
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
                    "ORB%cal_Def": "Opponent Rebot Ofensiu % (Rival ORB%)",
                    "FTR_Def": "Ràtio de Tirs Lliures Defensiu (Rival FTR)"
                }
                
                col_scat1, col_scat2 = st.columns(2)
                with col_scat1:
                    x_metric = st.selectbox(
                        "Eix X (Mètrica Ofensiva)", 
                        list(x_labels.keys()),
                        format_func=lambda x: x_labels[x],
                        key="league_x_selector"
                    )
                with col_scat2:
                    y_metric = st.selectbox(
                        "Eix Y (Mètrica Defensiva)", 
                        list(y_labels.keys()),
                        format_func=lambda y: y_labels[y],
                        key="league_y_selector"
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
                    text="Team", 
                    color="Visual_Group",
                    color_discrete_map=color_map,
                    size="Visual_Size",
                    size_max=16,
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
                    }
                )
                
                fig_scat.update_traces(
                    textposition='top center',
                    textfont=dict(size=10, color="#555555")
                )
                
                fig_scat.update_layout(
                    height=650,
                    xaxis=dict(range=x_range),
                    yaxis=dict(range=y_range)
                )
                
                fig_scat.add_vline(x=mean_x, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Atac")
                fig_scat.add_hline(y=mean_y, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Def")
                    
                st.plotly_chart(fig_scat, use_container_width=True)

            with tab_team_profile:
                scout_teams = sorted(list(offense_df["Team"].unique()))
                selected_profile_team = st.selectbox("Selecciona l'Equip per analitzar el seu Perfil de Tir", scout_teams)
                
                league_pps_val = calculate_league_average_pps(filtered_raw_off)
                
                st.subheader("📊 Perfil de Tir Ofensiu (Atac)")
                fig_vol_seasonal, fig_pps_seasonal = draw_team_seasonal_zone_charts(offense_df, selected_profile_team, league_pps_val)
                
                col_prof1, col_prof2 = st.columns(2)
                with col_prof1:
                    st.plotly_chart(fig_vol_seasonal, use_container_width=True)
                with col_prof2:
                    st.plotly_chart(fig_pps_seasonal, use_container_width=True)
                    
                st.markdown("---")
                st.subheader("📊 Perfil de Tir Defensiu (Defensa - Permès als Rivals)")
                st.write("Estudia quins llançaments concedeix aquest equip: els gràfics següents mostren el volum i l'eficiència (PPS) de tir dels rivals quan juguen contra ells.")
                
                fig_vol_def, fig_pps_def = draw_team_seasonal_zone_charts(defense_df, selected_profile_team, league_pps_val)
                
                col_def1, col_def2 = st.columns(2)
                with col_def1:
                    fig_vol_def.update_layout(title=f"Volum de Tirs Concedits de Mitjana - {selected_profile_team}")
                    st.plotly_chart(fig_vol_def, use_container_width=True)
                with col_def2:
                    fig_pps_def.update_layout(title=f"Eficiència de Tir Concedida (PPS) - {selected_profile_team}")
                    st.plotly_chart(fig_pps_def, use_container_width=True)

# ----------------- VIEW 3: SCOUTING JUGADORS (PERFIL EYBL CORREGIT) -----------------
elif view == "Scouting Jugadors":
    st.title(f"Scouting de Jugadors ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No s'han trobat acumulats de lliga. Comprova els fitxers d'acumulats de la temporada.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        # Neteja de tipus de dades a master_players
        master_players["GamesPlayed"] = pd.to_numeric(master_players["GamesPlayed"], errors='coerce').fillna(1)
        master_players["PTS"] = pd.to_numeric(master_players["PTS"], errors='coerce').fillna(0.0)
        master_players["eFG%"] = pd.to_numeric(master_players["eFG%"], errors='coerce').fillna(0.0)
        master_players["TS%"] = pd.to_numeric(master_players.get("TS%", 0.0), errors='coerce').fillna(0.0)
        master_players["FGA"] = pd.to_numeric(master_players["FGA"], errors='coerce').fillna(0.0)
        master_players["EFI"] = pd.to_numeric(master_players.get("EFI", 0.0), errors='coerce').fillna(0.0)
        master_players["USG%cal"] = pd.to_numeric(master_players.get("USG%cal", 0.0), errors='coerce').fillna(0.0)
        master_players["TO%cal"] = pd.to_numeric(master_players.get("TO%cal", 0.0), errors='coerce').fillna(0.0)
        master_players["FTR"] = pd.to_numeric(master_players.get("FTR", 0.0), errors='coerce').fillna(0.0)
        master_players["F+"] = pd.to_numeric(master_players.get("F+", 0.0), errors='coerce').fillna(0.0)
        
        for col in ["Rim FGA", "Paint FGA", "MR FGA", "Cor3 FGA", "ATB3 FGA", "Rim %", "Paint %", "MR %", "Cor3 %", "ATB3 %", "FT%"]:
            if col in master_players.columns:
                master_players[col] = pd.to_numeric(master_players[col], errors='coerce').fillna(0.0)
        
        master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
        
        # Carreguem tots els partits de la temporada un cop en memòria cau
        pbp_cache_key = get_dir_cache_key(BOX_DIR)
        season_logs_df = load_all_season_player_gamelogs(BOX_DIR, PBP_DIR, pbp_cache_key)
        
        # Selector Superior del Jugador
        scout_p_teams = ["Tots els equips"] + sorted(list(master_players["Team"].dropna().unique()))
        col_s1, col_s2 = st.columns([1.5, 2.5])
        with col_s1:
            filter_team_card = st.selectbox("Filtra jugadors per equip", scout_p_teams, index=0)
        with col_s2:
            if filter_team_card != "Tots els equips":
                roster_avail = sorted(list(master_players[master_players["Team"] == filter_team_card]["JUGADOR"].unique()))
            else:
                roster_avail = sorted(list(master_players["JUGADOR"].unique()))
            selected_player_card = st.selectbox("Selecciona el jugador per obrir la Fitxa d'Scouting", roster_avail, index=0)
            
        p_row = master_players[master_players["JUGADOR"] == selected_player_card].iloc[0]
        p_team = p_row["Team"]
        p_gp = int(p_row["GamesPlayed"])
        p_min = p_row.get("TIME", "00:00")
        p_num = extract_player_number(selected_player_card)
        p_clean_display = re.sub(r'^#\d+\s+', '', selected_player_card).strip()
        
        # Filtrem i ordenem cronològicament els partits reals del jugador seleccionat
        p_clean_target = clean_player_name_for_matching(selected_player_card)
        if not season_logs_df.empty:
            player_logs = season_logs_df[season_logs_df["Clean_Name"] == p_clean_target].copy()
            # Ordenem de la J1 a la J26 de forma ascendent
            player_logs = player_logs.sort_values(by=["Round_Num", "Filename"]).reset_index(drop=True)
        else:
            player_logs = pd.DataFrame()
            
        # PESTANYES DE NAVEGACIÓ: FITXA EYBL vs. RÀNQUING GLOBAL
        tab_eybl, tab_global_table = st.tabs(["👤 Fitxa d'Scouting Individual (Perfil EYBL)", "📋 Rànquings & Taula de Lliga"])
        
        with tab_eybl:
            # --- CAPÇALERA D'IDENTITAT ---
            st.markdown(
                f"""
                <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
                    <div style="display: flex; align-items: center; gap: 18px;">
                        <div style="background: linear-gradient(135deg, #1f77b4 0%, #0d3b66 100%); color: white; width: 62px; height: 62px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.4rem; font-weight: 800; border: 2px solid rgba(255,255,255,0.2);">
                            {p_num if p_num else "🏀"}
                        </div>
                        <div>
                            <h1 style="margin: 0; color: #f9fafb; font-size: 2.1rem; font-weight: 800; line-height: 1.1;">{p_clean_display}</h1>
                            <div style="color: #9ca3af; font-size: 1.05rem; font-weight: 500; margin-top: 4px;">{p_team} &nbsp;•&nbsp; Copa Catalunya</div>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800; line-height: 1.1;">{p_gp} <span style="font-size: 1.1rem; color: #9ca3af;">GP</span></div>
                        <div style="color: #9ca3af; font-size: 0.95rem; font-weight: 500; margin-top: 4px;">{p_min} <span style="font-size: 0.8rem;">MIN/G</span></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            col_c1, col_c2, col_c3 = st.columns([1.05, 1.35, 1.15])
            
            # ========== COLUMNA 1: PRODUCCIÓ, RADAR I TAXES DE TIR ==========
            with col_c1:
                # 1. Season production
                st.markdown(
                    f"""
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                        <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Season production</div>
                        <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 8px;">Per game</div>
                        <div style="display: flex; justify-content: space-between; align-items: center; text-align: center;">
                            <div>
                                <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800;">{p_row['PTS']:.1f}</div>
                                <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">PTS/G</div>
                            </div>
                            <div>
                                <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800;">{p_row['EFI']:.1f}</div>
                                <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">EFI/G</div>
                            </div>
                            <div>
                                <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800;">{p_row['FGA']:.1f}</div>
                                <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">FGA/G</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                # 2. Shot locations / Radars
                st.markdown(
                    """
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px; margin-bottom: 14px;">
                        <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Perfil de Tir (Radars)</div>
                        <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 6px;">Volum & Eficiència per zones vs Lliga</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                league_avg_dict = {
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
                league_max_dict = {
                    "Rim": master_players["Rim FGA"].max() or 1.0,
                    "Paint": master_players["Paint FGA"].max() or 1.0,
                    "MR": master_players["MR FGA"].max() or 1.0,
                    "Cor3": master_players["Cor3 FGA"].max() or 1.0,
                    "ATB3": master_players["ATB3 FGA"].max() or 1.0
                }
                
                fig_v_rad, fig_e_rad = draw_player_radar_charts(p_row, league_avg_dict, league_max_dict)
                radar_choice = st.radio("Tipus de radar", ["Eficiència (%)", "Volum (FGA)"], horizontal=True, label_visibility="collapsed")
                if radar_choice == "Eficiència (%)":
                    st.plotly_chart(fig_e_rad, use_container_width=True)
                else:
                    st.plotly_chart(fig_v_rad, use_container_width=True)
                
                # 3. Scoring by game (Gràfic cronològic net i ordenat)
                high_pts = player_logs["PTS"].max() if not player_logs.empty else p_row["PTS"]
                
                st.markdown(
                    f"""
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px 14px 4px 14px; margin-bottom: 14px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Scoring by game</div>
                                <div style="color: #6b7280; font-size: 0.75rem;">Season &bull; {len(player_logs)} partits registrats</div>
                            </div>
                            <div style="color: #2dd4bf; font-size: 0.82rem; font-weight: 700;">High {high_pts:.0f} pts</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                if not player_logs.empty:
                    # Si tenim la jornada exacta (ex: J1, J2) la fem servir; si no, P1, P2...
                    player_logs["Game_Label"] = [
                        f"{r['Round_Str']}" if r.get("Round_Str") else f"P{i+1}" 
                        for i, (_, r) in enumerate(player_logs.iterrows())
                    ]
                    
                    fig_sc_trend = px.bar(
                        player_logs, 
                        x="Game_Label", 
                        y="PTS",
                        hover_data={"Game_Label": True, "Opponent": True, "PTS": True, "TIME": True},
                        color_discrete_sequence=["#2dd4bf"]
                    )
                    fig_sc_trend.update_layout(
                        height=140,
                        margin=dict(l=10, r=10, t=10, b=20),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=False, title=None, tickfont=dict(size=9, color="#9ca3af")),
                        yaxis=dict(showgrid=True, gridcolor="#1f2937", title=None, tickfont=dict(size=9, color="#9ca3af"))
                    )
                    st.plotly_chart(fig_sc_trend, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.caption("No s'han trobat partits individuals als boxscores per fer el gràfic de tendència.")
                    
                # 4. Box shooting & rates (Càlculs 100% reals a partir de totals de tir)
                if not player_logs.empty and player_logs["3PA"].sum() > 0:
                    tot_3pm = int(player_logs["3PM"].sum())
                    tot_3pa = int(player_logs["3PA"].sum())
                    pct_3p = (tot_3pm / tot_3pa * 100.0)
                    
                    tot_2pm = int(player_logs["2PM"].sum())
                    tot_2pa = int(player_logs["2PA"].sum())
                    tot_fgm = tot_2pm + tot_3pm
                    tot_fga = tot_2pa + tot_3pa
                    pct_fg = (tot_fgm / tot_fga * 100.0) if tot_fga > 0 else 0.0
                    
                    tot_ftm = int(player_logs["FTM"].sum())
                    tot_fta = int(player_logs["FTA"].sum())
                    pct_ft = (tot_ftm / tot_fta * 100.0) if tot_fta > 0 else 0.0
                else:
                    # Càlcul ponderat per zones si no hi ha logs
                    c3_a = p_row.get("Cor3 FGA", 0.0)
                    atb_a = p_row.get("ATB3 FGA", 0.0)
                    tot_3pa_pg = c3_a + atb_a
                    c3_m = p_row.get("Cor3 FGM", c3_a * (p_row.get("Cor3 %", 0.0) / 100.0))
                    atb_m = p_row.get("ATB3 FGM", atb_a * (p_row.get("ATB3 %", 0.0) / 100.0))
                    tot_3pm_pg = c3_m + atb_m
                    pct_3p = (tot_3pm_pg / tot_3pa_pg * 100.0) if tot_3pa_pg > 0 else 0.0
                    tot_3pm = int(round(tot_3pm_pg * p_gp))
                    tot_3pa = int(round(tot_3pa_pg * p_gp))
                    
                    fga_2p = p_row.get("Rim FGA", 0) + p_row.get("Paint FGA", 0) + p_row.get("MR FGA", 0)
                    fgm_2p = (p_row.get("Rim FGA", 0) * p_row.get("Rim %", 0)/100 + 
                              p_row.get("Paint FGA", 0) * p_row.get("Paint %", 0)/100 + 
                              p_row.get("MR FGA", 0) * p_row.get("MR %", 0)/100)
                    tot_fgm_pg = fgm_2p + tot_3pm_pg
                    tot_fga_pg = fga_2p + tot_3pa_pg
                    pct_fg = (tot_fgm_pg / tot_fga_pg * 100.0) if tot_fga_pg > 0 else 0.0
                    tot_fgm = int(round(tot_fgm_pg * p_gp))
                    tot_fga = int(round(tot_fga_pg * p_gp))
                    
                    pct_ft = float(p_row.get("FT%", 73.2))
                    tot_ftm = int(round(float(p_row.get("FTM", 0)) * p_gp))
                    tot_fta = int(round(float(p_row.get("FTA", 0)) * p_gp))

                st.markdown(
                    f"""
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px;">
                        <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">Box shooting & rates</div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; text-align: center;">
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">FG%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{pct_fg:.1f}%</div>
                                <div style="color: #9ca3af; font-size: 0.65rem;">{tot_fgm}/{tot_fga}</div>
                            </div>
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">3P%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{pct_3p:.1f}%</div>
                                <div style="color: #9ca3af; font-size: 0.65rem;">{tot_3pm}/{tot_3pa}</div>
                            </div>
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">FT%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{pct_ft:.1f}%</div>
                                <div style="color: #9ca3af; font-size: 0.65rem;">{tot_ftm}/{tot_fta} if tot_fta > 0 else ""</div>
                            </div>
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">TS%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{p_row['TS%']:.1f}%</div>
                            </div>
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">eFG%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{p_row['eFG%']:.1f}%</div>
                            </div>
                            <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                                <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">USG%</div>
                                <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{p_row['USG%cal']:.1f}%</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
            # ========== COLUMNA 2: ADVANCED SCOUTING PROFILE (PERCENTILS) ==========
            with col_c2:
                st.markdown(
                    """
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; height: 100%;">
                        <div style="color: #f9fafb; font-size: 1.05rem; font-weight: 700; margin-bottom: 2px;">Advanced scouting profile</div>
                        <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 14px;">Percentils Copa Catalunya &bull; GP &ge; 3</div>
                    """,
                    unsafe_allow_html=True
                )
                
                qual_df = master_players[master_players["GamesPlayed"] >= 3].copy()
                if qual_df.empty or len(qual_df) < 5:
                    qual_df = master_players.copy()
                    
                def get_pctile(col_name, val, invert=False):
                    if col_name not in qual_df.columns or qual_df[col_name].empty:
                        return 50.0
                    s = qual_df[col_name].dropna()
                    if len(s) == 0:
                        return 50.0
                    p = (s < val).mean() * 100.0
                    if invert:
                        p = 100.0 - p
                    return max(1.0, min(99.0, float(p)))
                
                def render_eybl_bar(label, raw_val_str, pct_val):
                    bar_w = int(max(4, min(100, pct_val)))
                    return f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.82rem;">
                        <div style="color: #d1d5db; width: 155px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{label}</div>
                        <div style="color: #f9fafb; font-weight: 700; width: 55px; text-align: right; font-variant-numeric: tabular-nums;">{raw_val_str}</div>
                        <div style="flex-grow: 1; margin: 0 10px; background-color: #1f2937; height: 6px; border-radius: 3px; overflow: hidden;">
                            <div style="background-color: #2dd4bf; width: {bar_w}%; height: 100%; border-radius: 3px;"></div>
                        </div>
                        <div style="color: #9ca3af; font-size: 0.75rem; font-weight: 600; width: 45px; text-align: right;">P{pct_val:.1f}</div>
                    </div>
                    """
                    
                # BLOC 1: CREACIÓ & VOLUM DE TIR
                st.markdown("<div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 10px; margin-bottom: 8px;'>CREACIÓ & VOLUM DE TIR</div>", unsafe_allow_html=True)
                p_pts = get_pctile("PTS", p_row["PTS"])
                p_fga = get_pctile("FGA", p_row["FGA"])
                p_usg = get_pctile("USG%cal", p_row["USG%cal"])
                p_min_pct = get_pctile("MinPerGame", p_row["MinPerGame"])
                
                st.markdown(render_eybl_bar("Punts / Partit", f"{p_row['PTS']:.1f}", p_pts), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Tirs Intentats (FGA)", f"{p_row['FGA']:.1f}", p_fga), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Ús de Possessió (USG%)", f"{p_row['USG%cal']:.1f}%", p_usg), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Minuts / Partit", f"{p_row['MinPerGame']:.1f}'", p_min_pct), unsafe_allow_html=True)
                
                # BLOC 2: EFICIÈNCIA & ENCERT
                st.markdown("<div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 18px; margin-bottom: 8px;'>EFICIÈNCIA & ENCERT</div>", unsafe_allow_html=True)
                p_efg = get_pctile("eFG%", p_row["eFG%"])
                p_ts = get_pctile("TS%", p_row["TS%"])
                p_3p = get_pctile("ATB3 %", p_row.get("ATB3 %", 0))
                p_ft = get_pctile("FT%", p_row.get("FT%", 70))
                p_ftr = get_pctile("FTR", p_row.get("FTR", 0.2))
                
                st.markdown(render_eybl_bar("Tir Efectiu (eFG%)", f"{p_row['eFG%']:.1f}%", p_efg), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("True Shooting (TS%)", f"{p_row['TS%']:.1f}%", p_ts), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Encert Triple (3P%)", f"{pct_3p:.1f}%", p_3p), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Tirs Lliures (FT%)", f"{pct_ft:.1f}%", p_ft), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Forçar Tirs Lliures (FTR)", f"{p_row.get('FTR', 0):.2f}", p_ftr), unsafe_allow_html=True)
                
                # BLOC 3: VALORACIÓ & CONTRIBUCIÓ
                st.markdown("<div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 18px; margin-bottom: 8px;'>VALORACIÓ & CURA DE PILOTA</div>", unsafe_allow_html=True)
                p_efi = get_pctile("EFI", p_row["EFI"])
                p_to = get_pctile("TO%cal", p_row["TO%cal"], invert=True)
                p_fplus = get_pctile("F+", p_row.get("F+", 0))
                
                st.markdown(render_eybl_bar("Valoració / Partit", f"{p_row['EFI']:.1f}", p_efi), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Cura de Pilota (TO%)", f"{p_row['TO%cal']:.1f}%", p_to), unsafe_allow_html=True)
                st.markdown(render_eybl_bar("Faltes Rebudes (F+)", f"{p_row.get('F+', 0):.1f}", p_fplus), unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
                
            # ========== COLUMNA 3: DISTRIBUCIÓ DE TIR I PARTITS RECENTS ==========
            with col_c3:
                # 1. Shot distribution
                zones_scout = [
                    ("Rim", "Cèrcol (Rim)", p_row.get("Rim %", 0), league_avg_dict["Rim_Pct"], p_row.get("Rim FGA", 0)),
                    ("Paint", "Pintura (Paint)", p_row.get("Paint %", 0), league_avg_dict["Paint_Pct"], p_row.get("Paint FGA", 0)),
                    ("MR", "Mitja Distància (MR)", p_row.get("MR %", 0), league_avg_dict["MR_Pct"], p_row.get("MR FGA", 0)),
                    ("Cor3", "Corner 3", p_row.get("Cor3 %", 0), league_avg_dict["Cor3_Pct"], p_row.get("Cor3 FGA", 0)),
                    ("ATB3", "Top / Wing 3 (ATB)", p_row.get("ATB3 %", 0), league_avg_dict["ATB3_Pct"], p_row.get("ATB3 FGA", 0))
                ]
                
                rows_html = ""
                for z_id, z_name, z_pct, z_lg_pct, z_fga in zones_scout:
                    delta = z_pct - z_lg_pct
                    delta_color = "#2dd4bf" if delta >= 0 else "#f87171"
                    delta_sign = "+" if delta > 0 else ""
                    rows_html += f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; margin-bottom: 8px;">
                        <div style="width: 140px; color: #e5e7eb;">
                            <div style="font-weight: 600;">{z_name}</div>
                            <div style="font-size: 0.7rem; color: #9ca3af;">{z_fga:.1f} FGA/p</div>
                        </div>
                        <div style="width: 45px; text-align: right; color: #ffffff; font-weight: 700;">{z_pct:.1f}</div>
                        <div style="width: 50px; text-align: right; color: #9ca3af;">{z_lg_pct:.1f}</div>
                        <div style="width: 45px; text-align: right; color: {delta_color}; font-weight: 700;">{delta_sign}{delta:.1f}</div>
                    </div>
                    """
                
                shot_dist_html = f"""
                <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                    <div style="color: #f9fafb; font-size: 0.95rem; font-weight: 700; margin-bottom: 2px;">Shot distribution</div>
                    <div style="color: #9ca3af; font-size: 0.75rem; margin-bottom: 12px;">FG% vs Copa Cat &bull; delta in pp</div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #9ca3af; font-weight: 700; border-bottom: 1px solid #374151; padding-bottom: 4px; margin-bottom: 8px;">
                        <div style="width: 140px;">Zone / FG</div>
                        <div style="width: 45px; text-align: right;">FG%</div>
                        <div style="width: 50px; text-align: right;">COPA</div>
                        <div style="width: 45px; text-align: right;">Δ pp</div>
                    </div>
                    {rows_html}
                </div>
                """
                st.markdown(textwrap.dedent(shot_dist_html), unsafe_allow_html=True)
                
                # 2. Recent box scores
                recent_rows_html = ""
                if not player_logs.empty:
                    recent_5 = player_logs.tail(5).iloc[::-1]
                    for _, r_log in recent_5.iterrows():
                        fgm_tot = int(r_log["2PM"] + r_log["3PM"])
                        fga_tot = int(r_log["2PA"] + r_log["3PA"])
                        r_label = f"[{r_log['Round_Str']}] " if r_log.get("Round_Str") else ""
                        score_info = f" &bull; {r_log['Score_Result']}" if r_log.get("Score_Result") else ""
                        
                        recent_rows_html += f"""
                        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2937; padding: 7px 0;">
                            <div>
                                <div style="color: #ffffff; font-size: 0.82rem; font-weight: 700;">{r_label}vs {r_log['Opponent']}</div>
                                <div style="color: #9ca3af; font-size: 0.72rem;">{r_log['TIME']}{score_info} &bull; FG: {fgm_tot}/{fga_tot}</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="color: #2dd4bf; font-size: 0.95rem; font-weight: 800;">{r_log['PTS']:.0f} <span style="font-size: 0.75rem; color: #9ca3af;">PTS</span></div>
                                <div style="color: #9ca3af; font-size: 0.72rem;">{r_log['EFI']:.0f} EFI</div>
                            </div>
                        </div>
                        """
                else:
                    recent_rows_html = "<div style='color: #9ca3af; font-size: 0.8rem;'>Sense registre de partits individuals.</div>"

                recent_box_html = f"""
                <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px;">
                    <div style="color: #f9fafb; font-size: 0.95rem; font-weight: 700; margin-bottom: 2px;">Recent box scores</div>
                    <div style="color: #9ca3af; font-size: 0.75rem; margin-bottom: 10px;">PTS / EFI / MIN &bull; Últims partits jugats</div>
                    {recent_rows_html}
                </div>
                """
                st.markdown(textwrap.dedent(recent_box_html), unsafe_allow_html=True)
                
                # 2. Recent box scores (Cronologia exacta dels últims partits)
                st.markdown(
                    """
                    <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px;">
                        <div style="color: #f9fafb; font-size: 0.95rem; font-weight: 700; margin-bottom: 2px;">Recent box scores</div>
                        <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 10px;">PTS / EFI / MIN &bull; Últims partits jugats</div>
                    """,
                    unsafe_allow_html=True
                )
                
                if not player_logs.empty:
                    recent_5 = player_logs.tail(5).iloc[::-1]
                    for _, r_log in recent_5.iterrows():
                        fgm_tot = int(r_log["2PM"] + r_log["3PM"])
                        fga_tot = int(r_log["2PA"] + r_log["3PA"])
                        r_label = f"[{r_log['Round_Str']}] " if r_log.get("Round_Str") else ""
                        score_info = f" &bull; {r_log['Score_Result']}" if r_log.get("Score_Result") else ""
                        
                        st.markdown(
                            f"""
                            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2937; padding: 7px 0;">
                                <div>
                                    <div style="color: #f9fafb; font-size: 0.8rem; font-weight: 700;">{r_label}vs {r_log['Opponent']}</div>
                                    <div style="color: #6b7280; font-size: 0.72rem;">{r_log['TIME']}{score_info} &bull; FG: {fgm_tot}/{fga_tot}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="color: #2dd4bf; font-size: 0.95rem; font-weight: 800;">{r_log['PTS']:.0f} <span style="font-size: 0.75rem; color: #9ca3af;">PTS</span></div>
                                    <div style="color: #9ca3af; font-size: 0.72rem;">{r_log['EFI']:.0f} EFI</div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                else:
                    st.markdown("<div style='color: #9ca3af; font-size: 0.8rem;'>Sense registre de partits individuals.</div>", unsafe_allow_html=True)
                    
                st.markdown("</div>", unsafe_allow_html=True)
                
        # --- PESTANYA 2: RÀNQUINGS & TAULA GLOBAL DE LLIGA ---
        with tab_global_table:
            st.write("Motor de cerca i rànquing complet de tots els jugadors de la lliga:")
            
            col_filt1, col_filt2, col_filt3 = st.columns(3)
            with col_filt1:
                min_games = st.slider("Mínim de partits jugats", 1, int(master_players["GamesPlayed"].max() or 20), 3)
            with col_filt2:
                min_fga = st.slider("Mínim de FGA per partit", 0.0, float(master_players["FGA"].max() or 20.0), 2.0, step=0.5)
            with col_filt3:
                min_mins = st.slider("Mínim de minuts per partit", 0.0, float(master_players["MinPerGame"].max() or 40.0), 8.0, step=1.0)
                
            sorted_players = master_players[
                (master_players["GamesPlayed"] >= min_games) &
                (master_players["FGA"] >= min_fga) &
                (master_players["MinPerGame"] >= min_mins)
            ].sort_values("PTS", ascending=False)
            
            view_cols = [
                "JUGADOR", "Team", "GamesPlayed", "TIME", "FGA", "PTS", "eFG%", "TS%", "FT%", 
                "Rim FGA", "Rim %", "Paint FGA", "Paint %", "MR FGA", "MR %", "Cor3 FGA", "Cor3 %", "ATB3 FGA", "ATB3 %"
            ]
            
            player_index_config = {
                "JUGADOR": st.column_config.TextColumn("JUGADOR", width=240),
                "Team": st.column_config.TextColumn("Team", width=150)
            }
            for col in view_cols:
                if col not in ["JUGADOR", "Team"]:
                    if col == "TIME":
                        player_index_config[col] = st.column_config.TextColumn(col, width=65)
                    elif "%" in col:
                        player_index_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width=65)
                    else:
                        player_index_config[col] = st.column_config.NumberColumn(col, width=60)
            
            st.dataframe(
                sorted_players[view_cols].style.format({
                    "TIME": "{}", 
                    "FGA": "{:.1f}",
                    "PTS": "{:.1f}",
                    "eFG%": "{:.2f}%",
                    "TS%": "{:.2f}%",
                    "FT%": "{:.2f}%",
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

# ----------------- VIEW 4: SCOUTING EQUIPS -----------------
elif view == "Scouting Equips":
    st.title(f"Scouting Equips ({selected_season.replace('_', ' ')})")
    
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
            col_logo_A, col_vs, col_logo_B = st.columns([1, 0.5, 1])
            with col_logo_A:
                logo_path_A = get_team_logo_path(team_A, selected_season)
                if logo_path_A:
                    st.markdown(get_logo_html_centered(logo_path_A, max_height=100, max_width=140), unsafe_allow_html=True)
                else:
                    st.subheader(team_A)
            with col_vs:
                st.markdown("<h2 style='text-align: center; line-height: 100px; color: gray;'>VS</h2>", unsafe_allow_html=True)
            with col_logo_B:
                logo_path_B = get_team_logo_path(team_B, selected_season)
                if logo_path_B:
                    st.markdown(get_logo_html_centered(logo_path_B, max_height=100, max_width=140), unsafe_allow_html=True)
                else:
                    st.subheader(team_B)
                    
            st.markdown("---")
            st.subheader("Comparativa de Rànquings i Eficiència de l'Equip")
            
            off_ranks = offense_df.copy()
            def_ranks = defense_df.copy()
            
            for df_t in [off_ranks, def_ranks]:
                fga_2p = df_t["Rim FGA"] + df_t["Paint FGA"] + df_t["MR FGA"]
                fgm_2p = df_t["Rim FGM"] + df_t["Paint FGM"] + df_t["MR FGM"]
                df_t["%T2"] = (fgm_2p / fga_2p * 100.0).fillna(0.0)
                
                fga_3p = df_t["Cor3 FGA"] + df_t["ATB3 FGA"]
                fgm_3p = df_t["Cor3 FGM"] + df_t["ATB3 FGM"]
                df_t["%T3"] = (fgm_3p / fga_3p * 100.0).fillna(0.0)
                
                if "FT%" in df_t.columns:
                    df_t["%T1"] = df_t["FT%"]
                elif "FT_Pct" in df_t.columns:
                    df_t["%T1"] = df_t["FT_Pct"]
                else:
                    df_t["%T1"] = 72.0
                    
                df_t["Us_tir_2"] = fga_2p
                df_t["Us_Tir_3"] = fga_3p
                df_t["Pts_T2"] = (2.0 * fgm_2p / fga_2p).fillna(0.0)
                df_t["Pts_T3"] = (3.0 * fgm_3p / fga_3p).fillna(0.0)

            # Offensive Rankings (Higher is better)
            off_ranks["OER_Rank"] = off_ranks["OERcal"].rank(ascending=False, method="min")
            off_ranks["eFG_Rank"] = off_ranks["eFG%"].rank(ascending=False, method="min")
            off_ranks["ORB_Rank"] = off_ranks["ORB%cal"].rank(ascending=False, method="min")
            off_ranks["FTR_Rank"] = off_ranks["FTR"].rank(ascending=False, method="min")
            off_ranks["Pace_Rank"] = off_ranks["POSScal"].rank(ascending=False, method="min")
            off_ranks["TOV_Rank"] = off_ranks["TOV%cal"].rank(ascending=True, method="min")
            off_ranks["T1_Rank"] = off_ranks["%T1"].rank(ascending=False, method="min")
            off_ranks["T2_Rank"] = off_ranks["%T2"].rank(ascending=False, method="min")
            off_ranks["T3_Rank"] = off_ranks["%T3"].rank(ascending=False, method="min")
            off_ranks["Us_T2_Rank"] = off_ranks["Us_tir_2"].rank(ascending=False, method="min")
            off_ranks["Us_T3_Rank"] = off_ranks["Us_Tir_3"].rank(ascending=False, method="min")
            off_ranks["Pts_T2_Rank"] = off_ranks["Pts_T2"].rank(ascending=False, method="min")
            off_ranks["Pts_T3_Rank"] = off_ranks["Pts_T3"].rank(ascending=False, method="min")
            
            # Defensive Rankings (Lower is better)
            def_ranks["DER_Rank"] = def_ranks["OERcal"].rank(ascending=True, method="min")
            def_ranks["eFG_Def_Rank"] = def_ranks["eFG%"].rank(ascending=True, method="min")
            def_ranks["TOV_Def_Rank"] = def_ranks["TOV%cal"].rank(ascending=False, method="min")
            def_ranks["ORB_Def_Rank"] = def_ranks["ORB%cal"].rank(ascending=True, method="min")
            def_ranks["FTR_Def_Rank"] = def_ranks["FTR"].rank(ascending=True, method="min")
            def_ranks["Pts_T2_Def_Rank"] = def_ranks["Pts_T2"].rank(ascending=True, method="min")
            def_ranks["Pts_T3_Def_Rank"] = def_ranks["Pts_T3"].rank(ascending=True, method="min")
            
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
                    "FTR_Def": (t_def["FTR"], int(t_def["FTR_Def_Rank"])),
                    "T1": (t_off["%T1"], int(t_off["T1_Rank"])),
                    "T2": (t_off["%T2"], int(t_off["T2_Rank"])),
                    "T3": (t_off["%T3"], int(t_off["T3_Rank"])),
                    "Us_T2": (t_off["Us_tir_2"], int(t_off["Us_T2_Rank"])),
                    "Us_T3": (t_off["Us_Tir_3"], int(t_off["Us_T3_Rank"])),
                    "Pts_T2": (t_off["Pts_T2"], int(t_off["Pts_T2_Rank"])),
                    "Pts_T3": (t_off["Pts_T3"], int(t_off["Pts_T3_Rank"])),
                    "Pts_T2_Def": (t_def["Pts_T2"], int(t_def["Pts_T2_Def_Rank"])),
                    "Pts_T3_Def": (t_def["Pts_T3"], int(t_def["Pts_T3_Def_Rank"]))
                }
                
            stats_A = get_team_scout_stats(team_A)
            stats_B = get_team_scout_stats(team_B)
            
            def get_normalized_strength(key, val, off_df, def_df):
                is_def_metric = key in ["DER", "eFG_Def", "TOV_Def", "ORB_Def", "FTR_Def", "Pts_T2_Def", "Pts_T3_Def"]
                df_target = def_df if is_def_metric else off_df
                
                col_map = {
                    "OER": "OERcal", "DER": "OERcal", "Pace": "POSScal",
                    "eFG": "eFG%", "TOV": "TOV%cal", "ORB": "ORB%cal", "FTR": "FTR",
                    "eFG_Def": "eFG%", "TOV_Def": "TOV%cal", "ORB_Def": "ORB%cal", "FTR_Def": "FTR",
                    "T1": "%T1", "T2": "%T2", "T3": "%T3",
                    "Us_T2": "Us_tir_2", "Us_T3": "Us_Tir_3",
                    "Pts_T2": "Pts_T2", "Pts_T3": "Pts_T3",
                    "Pts_T2_Def": "Pts_T2", "Pts_T3_Def": "Pts_T3"
                }
                col_name = col_map[key]
                
                min_v = float(df_target[col_name].min())
                max_v = float(df_target[col_name].max())
                
                if max_v == min_v:
                    return 0.5
                    
                lower_is_better = key in ["DER", "TOV", "eFG_Def", "ORB_Def", "FTR_Def", "Pts_T2_Def", "Pts_T3_Def"]
                
                if lower_is_better:
                    norm = (max_v - val) / (max_v - min_v)
                else:
                    norm = (val - min_v) / (max_v - min_v)
                return max(0.0, min(1.0, float(norm)))

            mirror_data = []
            metrics_mapping = [
                ("Pace", "Ritme (Pace)", "{:.1f}"),
                ("OER", "Ràting Ofensiu (OER)", "{:.2f}"),
                ("DER", "Ràting Defensiu (DER)", "{:.2f}"),
                ("eFG", "eFG% Ofensiu", "{:.2f}%"),
                ("ORB", "Rebot Ofensiu % (OR%)", "{:.2f}%"),
                ("TOV", "Pèrdues Ofensiu % (TOV%)", "{:.2f}%"),
                ("FTR", "Ràtio de Lliures Atac (FTR)", "{:.2f}"),
                ("eFG_Def", "eFG% Defensiu (Rival)", "{:.2f}%"),
                ("ORB_Def", "Rebot Defensiu % (Rival OR%)", "{:.2f}%"),
                ("TOV_Def", "Pèrdues Defensiu % (TO% Rival)", "{:.2f}%"),
                ("FTR_Def", "Ràtio de Lliures Defensiu (Rival FTR)", "{:.2f}"),
                ("T1", "Percentatge Tirs Lliures (%T1)", "{:.2f}%"),
                ("T2", "Percentatge Tirs de 2 (%T2)", "{:.2f}%"),
                ("T3", "Percentatge Tirs de 3 (%T3)", "{:.2f}%"),
                ("Us_T2", "Volum Tirs de 2 (Us tir 2)", "{:.1f}/p"),
                ("Us_T3", "Volum Tirs de 3 (Us Tir 3)", "{:.1f}/p"),
                ("Pts_T2", "Punts per llançament 2P (Pts/T2)", "{:.2f} PPS"),
                ("Pts_T3", "Punts per llançament 3P (Pts/T3)", "{:.2f} PPS"),
                ("Pts_T2_Def", "PPS permesos de 2P (Pts T2 riv)", "{:.2f} PPS"),
                ("Pts_T3_Def", "PPS permesos de 3P (Pts T3 riv)", "{:.2f} PPS")
            ]
            
            for key, name, fmt in metrics_mapping:
                val_A, rank_A = stats_A[key]
                val_B, rank_B = stats_B[key]
                
                strength_A = get_normalized_strength(key, val_A, off_ranks, def_ranks)
                strength_B = get_normalized_strength(key, val_B, off_ranks, def_ranks)
                
                str_A = f"{cat_rank(rank_A)} ({fmt.format(val_A)})"
                str_B = f"{cat_rank(rank_B)} ({fmt.format(val_B)})"
                
                mirror_data.append({
                    "Fortalesa (A)": strength_A,
                    f"Rànquing ({team_A})": str_A,
                    "Mètrica de Lliga": name,
                    f"Rànquing ({team_B})": str_B,
                    "Fortalesa (B)": strength_B
                })
                
            mirror_df = pd.DataFrame(mirror_data)
            mirror_col_config = {
                "Fortalesa (A)": st.column_config.ProgressColumn("Fortalesa", min_value=0.0, max_value=1.0, width="medium"),
                f"Rànquing ({team_A})": st.column_config.TextColumn(f"Rànquing ({team_A})", width=150),
                "Mètrica de Lliga": st.column_config.TextColumn("Mètrica de Lliga", width=300),
                f"Rànquing ({team_B})": st.column_config.TextColumn(f"Rànquing ({team_B})", width=150),
                "Fortalesa (B)": st.column_config.ProgressColumn("Fortalesa", min_value=0.0, max_value=1.0, width="medium")
            }
            st.dataframe(
                mirror_df,
                use_container_width=False,
                column_config=mirror_col_config,
                hide_index=True,
                height=760
            )
            
            st.markdown("---")
            st.subheader("📊 Ràdars Tàctics de l'Atac vs Defensa (4 Factors)")
            st.write("Analitza la identitat tàctica d'ambdós rivals: la línia blava representa la força de fons ofensiva i la taronja la seva fortalesa defensiva en el rànquing de lliga.")
            
            strengths_A_off = [get_normalized_strength("OER", stats_A["OER"][0], off_ranks, def_ranks), get_normalized_strength("eFG", stats_A["eFG"][0], off_ranks, def_ranks), get_normalized_strength("TOV", stats_A["TOV"][0], off_ranks, def_ranks), get_normalized_strength("ORB", stats_A["ORB"][0], off_ranks, def_ranks), get_normalized_strength("FTR", stats_A["FTR"][0], off_ranks, def_ranks)]
            strengths_A_def = [get_normalized_strength("DER", stats_A["DER"][0], off_ranks, def_ranks), get_normalized_strength("eFG_Def", stats_A["eFG_Def"][0], off_ranks, def_ranks), get_normalized_strength("TOV_Def", stats_A["TOV_Def"][0], off_ranks, def_ranks), get_normalized_strength("ORB_Def", stats_A["ORB_Def"][0], off_ranks, def_ranks), get_normalized_strength("FTR_Def", stats_A["FTR_Def"][0], off_ranks, def_ranks)]
            
            strengths_B_off = [get_normalized_strength("OER", stats_B["OER"][0], off_ranks, def_ranks), get_normalized_strength("eFG", stats_B["eFG"][0], off_ranks, def_ranks), get_normalized_strength("TOV", stats_B["TOV"][0], off_ranks, def_ranks), get_normalized_strength("ORB", stats_B["ORB"][0], off_ranks, def_ranks), get_normalized_strength("FTR", stats_B["FTR"][0], off_ranks, def_ranks)]
            strengths_B_def = [get_normalized_strength("DER", stats_B["DER"][0], off_ranks, def_ranks), get_normalized_strength("eFG_Def", stats_B["eFG_Def"][0], off_ranks, def_ranks), get_normalized_strength("TOV_Def", stats_B["TOV_Def"][0], off_ranks, def_ranks), get_normalized_strength("ORB_Def", stats_B["ORB_Def"][0], off_ranks, def_ranks), get_normalized_strength("FTR_Def", stats_B["FTR_Def"][0], off_ranks, def_ranks)]
            
            fig_rad_A = draw_scouting_4f_radar_chart(team_A, strengths_A_off, strengths_A_def)
            fig_rad_B = draw_scouting_4f_radar_chart(team_B, strengths_B_off, strengths_B_def)
            
            col_scout_rad1, col_scout_rad2 = st.columns(2)
            with col_scout_rad1:
                st.plotly_chart(fig_rad_A, use_container_width=True)
            with col_scout_rad2:
                st.plotly_chart(fig_rad_B, use_container_width=True)
            
            st.markdown("---")
            st.subheader("Anàlisi Comparatiu per Jugador (Volum i PPS per Trams)")
            
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
                
            st.markdown("---")
            st.subheader("Anàlisi Avançat de Quintets, Rotació i Parelles")
            st.write("Estudia les rotacions de qualsevol dels dos equips: revisa el rendiment dels seus quintets, l'impacte net de cada jugador de la plantilla (On-Off) o la coincidència de parelles.")
            
            selected_scout_lineup_team = st.radio("Selecciona l'equip a analitzar:", [team_A, team_B], horizontal=True)
            
            pbp_cache_key = get_dir_cache_key(PBP_DIR)
            agg_lineups, combined_df = load_and_aggregate_season_lineups(PBP_DIR, selected_scout_lineup_team, pbp_cache_key)
            
            if agg_lineups.empty or combined_df.empty:
                st.info(f"No s'han trobat dades de Play-by-Play per a {selected_scout_lineup_team} en aquesta temporada.")
            else:
                st.write(f"#### 🏀 Quintets Acumulats de **{selected_scout_lineup_team}**")
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
                        
                st.dataframe(
                    agg_lineups[selected_lineup_cols], 
                    use_container_width=False,
                    column_config=lineup_col_config,
                    hide_index=True
                )
                
                st.write("")
                st.write(f"#### 📊 Mapa d'Impacte On-Off vs. Eficiència de la Plantilla - {selected_scout_lineup_team}")
                st.write("Aquest gràfic analitza l'impacte net de cada jugador de rotació: l'**Eix X** mostra la millora/gir de l'equip a pista (On - Off) i l'**Eix Y** mostra l'eficiència absoluta quan el jugador juga. El quadrant superior dret sempre representa el màxim impacte positiu.")
                
                roster = set()
                for c in ["P1", "P2", "P3", "P4", "P5"]:
                    if c in combined_df.columns:
                        roster.update(combined_df[c].dropna().unique())
                roster_list = sorted(list(roster))
                
                roster_on_off_df = calculate_all_players_on_off_profiles(combined_df, roster_list)
                
                if not roster_on_off_df.empty:
                    col_met1, col_met2 = st.columns([2, 2])
                    with col_met1:
                        scout_metric = st.selectbox(
                            "Mètrica d'Impacte per al Gràfic de Dispersió",
                            ["eFG% Ofensiu (Atac)", "eFG% Defensiu (Rival)", "Pèrdues % (TO%)", "Pèrdues % Rivals Forçades (TO% Rival)"],
                            key="scout_team_onoff_metric"
                        )
                    
                    metric_map = {
                        "eFG% Ofensiu (Atac)": ("Net_eFG_Off", "On_eFG_Off", "eFG% Atac a Pista", "Millora eFG% Atac (On-Off)"),
                        "eFG% Defensiu (Rival)": ("Net_eFG_Def", "On_eFG_Def", "eFG% Defensiu a Pista", "Millora eFG% Defensiu (On-Off)"),
                        "Pèrdues % (TO%)": ("Net_TO_Off", "On_TO_Off", "Pèrdues % a Pista", "Millora TO% (On-Off)"),
                        "Pèrdues % Rivals Forçades (TO% Rival)": ("Net_TO_Def", "On_TO_Def", "Pèrdues Rivals a Pista", "Millora TO% Rival (On-Off)")
                    }
                    
                    x_col, y_col, y_label, x_label = metric_map[scout_metric]
                    
                    fig_scat_onoff = px.scatter(
                        roster_on_off_df,
                        x=x_col,
                        y=y_col,
                        hover_name="JUGADOR",
                        text="JUGADOR", 
                        title=f"Mapa d'Impacte On-Off - {selected_scout_lineup_team} ({scout_metric})",
                        labels={x_col: x_label, y_col: y_label},
                        color_discrete_sequence=[CB_BLUE]
                    )
                    
                    fig_scat_onoff.update_traces(
                        textposition='top center',
                        textfont=dict(size=10, color="#444444")
                    )
                    
                    fig_scat_onoff.add_vline(x=0.0, line_dash="dash", line_color=CB_ORANGE, annotation_text="Llindar Canvi Zero", annotation_position="top right")
                    
                    if x_col == "Net_eFG_Off":
                        true_avg_y = float(offense_df[offense_df["Team"] == selected_scout_lineup_team]["eFG%"].iloc[0])
                        avg_line_label = f"Mitjana Atac {selected_scout_lineup_team} ({true_avg_y:.2f}%)"
                    elif x_col == "Net_eFG_Def":
                        true_avg_y = float(defense_df[defense_df["Team"] == selected_scout_lineup_team]["eFG%"].iloc[0])
                        avg_line_label = f"Mitjana Def {selected_scout_lineup_team} ({true_avg_y:.2f}%)"
                    else:
                        true_avg_y = roster_on_off_df[y_col].mean()
                        avg_line_label = f"Mitjana Plantilla a Pista ({true_avg_y:.2f}%)"
                    
                    fig_scat_onoff.add_hline(y=true_avg_y, line_dash="dot", line_color="gray", annotation_text=avg_line_label, annotation_position="top left")
                    
                    if x_col in ["Net_eFG_Def", "Net_TO_Off"]:
                        fig_scat_onoff.update_xaxes(autorange="reversed")
                    if y_col in ["On_eFG_Def", "On_TO_Off"]:
                        fig_scat_onoff.update_yaxes(autorange="reversed")
                        
                    st.plotly_chart(fig_scat_onoff, use_container_width=True)

                st.write("")
                st.write(f"#### 👥 Anàlisi de Parelles i Coincidència de **{selected_scout_lineup_team}**")
                
                col_pX, col_pY = st.columns(2)
                with col_pX:
                    player_X = st.selectbox("Selecciona el Jugador A (Principal)", roster_list, index=0, key="scout_player_x")
                with col_pY:
                    roster_with_none = ["Cap (Només Jugador A)"] + [p for p in roster_list if p != player_X]
                    player_Y = st.selectbox("Selecciona el Jugador B (Opcional)", roster_with_none, index=0, key="scout_player_y")
                    
                if player_Y == "Cap (Només Jugador A)":
                    on_court = combined_df[combined_df["Lineup"].str.contains(player_X, na=False)]
                    off_court = combined_df[~combined_df["Lineup"].str.contains(player_X, na=False)]
                    
                    st.write(f"Rendiment global d'On/Off per a **{player_X}**:")
                    col_on, col_off, col_net = st.columns(3)
                    
                    plus_on = on_court["+/-"].sum() if not on_court.empty else 0.0
                    plus_off = off_court["+/-"].sum() if not off_court.empty else 0.0
                    net_impact = plus_on - plus_off
                    
                    with col_on:
                        st.metric(
                            label=f"A Pista ({player_X})", 
                            value=f"{plus_on:+.1f}",
                            help=f"Equip jugant amb el Jugador A a pista. Punts a favor: {on_court['PTS_For'].sum():.0f}, Punts en contra: {on_court['PTS_Agn'].sum():.0f}"
                        )
                    with col_off:
                        st.metric(
                            label=f"A la Banqueta (Off-Court)", 
                            value=f"{plus_off:+.1f}",
                            help=f"Equip jugant sense el Jugador A a pista. Punts a favor: {off_court['PTS_For'].sum():.0f}, Punts en contra: {off_court['PTS_Agn'].sum():.0f}"
                        )
                    with col_net:
                        st.metric(
                            label="Impacte NET (On-Off)",
                            value=f"{net_impact:+.1f}",
                            help=f"Diferencial net de l'equip amb el jugador a pista vs. a la banqueta. Càlcul: {plus_on:+.1f} - ({plus_off:+.1f}) = {net_impact:+.1f}"
                        )
                    
                    def highlight_on_off_profile_diff(df):
                        style_df = pd.DataFrame('', index=df.index, columns=df.columns)
                        net_idx = 2
                        rules = {
                            "off eFG%": True,
                            "def eFG%": False,
                            "to%": False,
                            "to%ag": True,
                            "RO/tram": True,
                            "RO Ag/tram": False,
                            "RD/tram": True,
                            "RD Ag/tram": False
                        }
                        for col, positive_is_good in rules.items():
                            if col in df.columns:
                                val = df.loc[net_idx, col]
                                if positive_is_good:
                                    if val > 0:
                                        style_df.loc[net_idx, col] = 'background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;'
                                    elif val < 0:
                                        style_df.loc[net_idx, col] = 'background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;'
                                else:
                                    if val < 0:
                                        style_df.loc[net_idx, col] = 'background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;'
                                    elif val > 0:
                                        style_df.loc[net_idx, col] = 'background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;'
                        return style_df

                    target_clean_name = clean_player_name_for_matching(player_X)
                    scout_player_rows = master_players[master_players["JUGADOR"].apply(clean_player_name_for_matching) == target_clean_name]
                    
                    if not scout_player_rows.empty:
                        scout_player_row = scout_player_rows.iloc[0]
                        avg_time = scout_player_row.get("TIME", "00:00")
                        games_played_val = int(pd.to_numeric(scout_player_row.get("GamesPlayed", 1), errors="coerce"))
                    else:
                        avg_time = "00:00"
                        games_played_val = 0

                    trams_on = len(on_court)
                    trams_off = len(off_court)
                    
                    o_efg_on, d_efg_on, to_on, to_ag_on, ro_on, ro_ag_on, rd_on, rd_ag_on = calculate_combo_stats_metrics(on_court)
                    o_efg_off, d_efg_off, to_off, to_ag_off, ro_off, ro_ag_off, rd_off, rd_ag_off = calculate_combo_stats_metrics(off_court)
                    
                    ro_on_s = ro_on / trams_on if trams_on > 0 else 0.0
                    ro_off_s = ro_off / trams_off if trams_off > 0 else 0.0
                    ro_ag_on_s = ro_ag_on / trams_on if trams_on > 0 else 0.0
                    ro_ag_off_s = ro_ag_off / trams_off if trams_off > 0 else 0.0
                    
                    rd_on_s = rd_on / trams_on if trams_on > 0 else 0.0
                    rd_off_s = rd_off / trams_off if trams_off > 0 else 0.0
                    rd_ag_on_s = rd_ag_on / trams_on if trams_on > 0 else 0.0
                    rd_ag_off_s = rd_ag_off / trams_off if trams_off > 0 else 0.0
                    
                    profile_rows = [
                        {
                            "Estat": f"A Pista ({player_X})",
                            "Trams": trams_on,
                            "off eFG%": o_efg_on, "def eFG%": d_efg_on,
                            "to%": to_on, "to%ag": to_ag_on,
                            "RO/tram": ro_on_s, "RO Ag/tram": ro_ag_on_s,
                            "RD/tram": rd_on_s, "RD Ag/tram": rd_ag_on_s
                        },
                        {
                            "Estat": "A la Banqueta (Off)",
                            "Trams": trams_off,
                            "off eFG%": o_efg_off, "def eFG%": d_efg_off,
                            "to%": to_off, "to%ag": to_ag_off,
                            "RO/tram": ro_off_s, "RO Ag/tram": ro_ag_off_s,
                            "RD/tram": rd_off_s, "RD Ag/tram": rd_ag_off_s
                        },
                        {
                            "Estat": "Diferencial (NET)",
                            "Trams": trams_on - trams_off,
                            "off eFG%": o_efg_on - o_efg_off, "def eFG%": d_efg_on - d_efg_off,
                            "to%": to_on - to_off, "to%ag": to_ag_on - to_ag_off,
                            "RO/tram": ro_on_s - ro_off_s, "RO Ag/tram": ro_ag_on_s - ro_ag_off_s,
                            "RD/tram": rd_on_s - rd_off_s, "RD Ag/tram": rd_ag_on_s - rd_ag_off_s
                        }
                    ]
                    
                    profile_df = pd.DataFrame(profile_rows)
                    
                    profile_config = {
                        "Estat": st.column_config.TextColumn("Estat", width=180),
                        "Trams": st.column_config.NumberColumn("Trams", format="%.0f", width=55),
                        "off eFG%": st.column_config.NumberColumn("eFG% Atac", format="%.1f%%", width=95),
                        "def eFG%": st.column_config.NumberColumn("eFG% Def", format="%.1f%%", width=85),
                        "to%": st.column_config.NumberColumn("Pèrdues %", format="%.1f%%", width=95),
                        "to%ag": st.column_config.NumberColumn("Pèrd % riv", format="%.1f%%", width=95),
                        "RO/tram": st.column_config.NumberColumn("RO/tram", format="%.2f", width=75),
                        "RO Ag/tram": st.column_config.NumberColumn("RO riv/tram", format="%.2f", width=95),
                        "RD/tram": st.column_config.NumberColumn("RD/tram", format="%.2f", width=75),
                        "RD Ag/tram": st.column_config.NumberColumn("RD riv/tram", format="%.2f", width=95)
                    }
                    
                    st.write("")
                    st.write(f"📊 **Perfil de Rendiment Detallat d'On/Off per a {player_X}:**")
                    st.caption(f"⏱️ **Minuts de mitjana per partit:** {avg_time} | 🏆 **Partits jugats total:** {games_played_val} | 🔄 **Trams jugats:** {trams_on}")
                    st.dataframe(
                        profile_df.style.apply(highlight_on_off_profile_diff, axis=None), 
                        use_container_width=False,
                        column_config=profile_config,
                        hide_index=True
                    ) 
                    st.write("")
                    teammate_stats = []
                    for teammate in roster_list:
                        if teammate == player_X:
                            continue
                        
                        both_on_raw = combined_df[
                            combined_df["Lineup"].str.contains(player_X, na=False) & 
                            combined_df["Lineup"].str.contains(teammate, na=False)
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
                            "Company": st.column_config.TextColumn("Company", width=220),
                            "+/- Acumulat": st.column_config.NumberColumn("+/-", width=65),
                            "Partits": st.column_config.NumberColumn("Partits", width=60),
                            "Trams": st.column_config.NumberColumn("Trams", width=60),
                            "off eFG%": st.column_config.NumberColumn("eFG% Atac", format="%.1f%%", width=95),
                            "def eFG%": st.column_config.NumberColumn("eFG% Def", format="%.1f%%", width=85),
                            "to%": st.column_config.NumberColumn("Pèrdues %", format="%.1f%%", width=95),
                            "to%ag": st.column_config.NumberColumn("Pèrd % riv", format="%.1f%%", width=95),
                            "ro": st.column_config.NumberColumn("RO", width=50),
                            "ro Ag": st.column_config.NumberColumn("RO riv", width=65),
                            "rd": st.column_config.NumberColumn("RD", width=50),
                            "rd ag": st.column_config.NumberColumn("RD riv", width=65)
                        }
                        with col_best:
                            st.write(f"👍 **Millors companyies per a {player_X}**")
                            styled_best = teammate_df.head(3).style.apply(highlight_teammate_outliers)
                            st.dataframe(
                                styled_best, 
                                use_container_width=False, 
                                hide_index=True, 
                                column_config=t_config
                            )
                        with col_worst:
                            st.write(f"👎 **Pitjors companyies per a {player_X}**")
                            styled_worst = teammate_df.tail(3).sort_values("+/- Acumulat", ascending=True).style.apply(highlight_teammate_outliers)
                            st.dataframe(
                                styled_worst, 
                                use_container_width=False, 
                                hide_index=True, 
                                column_config=t_config
                            )
                else:
                    both_on = combined_df[combined_df["Lineup"].str.contains(player_X, na=False) & combined_df["Lineup"].str.contains(player_Y, na=False)]
                    only_X = combined_df[combined_df["Lineup"].str.contains(player_X, na=False) & ~combined_df["Lineup"].str.contains(player_Y, na=False)]
                    only_Y = combined_df[~combined_df["Lineup"].str.contains(player_X, na=False) & combined_df["Lineup"].str.contains(player_Y, na=False)]
                    both_off = combined_df[~combined_df["Lineup"].str.contains(player_X, na=False) & ~combined_df["Lineup"].str.contains(player_Y, na=False)]
                    
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