import base64
import hmac
import os
import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data_loader import (
    get_available_seasons,
    load_all_game_options,
    parse_boxscore,
    parse_pbp,
    parse_aggregate,
    resolve_path_case_insensitive,
    estimate_game_duration,
    find_best_matching_pbp,
    parse_time_to_minutes,
    tag_shot_team,
    get_dir_cache_key,
    load_and_aggregate_season_lineups,
    load_all_raw_game_boxscores,
    calculate_combo_stats_metrics,
    get_team_logo_path,
    get_team_logo_base64_url,
)
from utils.court_visualizer import (
    draw_boxscore_zone_charts,
    draw_player_radar_charts,
    draw_team_seasonal_zone_charts,
    draw_scouting_4f_radar_chart,
)

# Page config (ha de ser la primera crida de Streamlit)
st.set_page_config(page_title="Anàlisi de Bàsquet - Staff", layout="wide")

RAW_DIR = "data/raw"
CB_BLUE = "#1f77b4"
CB_ORANGE = "#ff7f0e"
CB_NEUTRAL = "#4a4a4a"

ZONES = ["Rim", "Paint", "MR", "Cor3", "ATB3"]
LINEUP_PLAYER_COLS = ["P1", "P2", "P3", "P4", "P5"]

STYLE_GOOD = "background-color: rgba(214, 39, 40, 0.18); color: #d62728; font-weight: bold;"
STYLE_BAD = "background-color: rgba(31, 119, 180, 0.18); color: #1f77b4; font-weight: bold;"


# =====================================================================
# SEGURETAT
# =====================================================================
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
            if hmac.compare_digest(entered_password.encode(), str(correct_password).encode()):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Contrasenya incorrecta.")
        st.stop()


check_password()


# =====================================================================
# HELPERS GENERALS
# =====================================================================
def render_html(html_str):
    """Renderitza HTML eliminant sagnats perquè Markdown no el tracti com a codi."""
    clean = "".join(line.strip() for line in html_str.splitlines())
    st.markdown(clean, unsafe_allow_html=True)


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
    if not isinstance(num, int):
        return "-"
    if num == 1:
        return "1er"
    if num == 2:
        return "2on"
    if num == 3:
        return "3er"
    if num == 4:
        return "4rt"
    return f"{num}è"


def safe_rank(val):
    """Converteix un rànquing a enter o retorna '-' si és NaN."""
    try:
        if val is None or pd.isna(val):
            return "-"
        return int(float(val))
    except Exception:
        return "-"


def safe_fmt(fmt, val):
    """Aplica un format a un valor; retorna '–' si és NaN/None."""
    try:
        if val is None or pd.isna(val):
            return "–"
        return fmt.format(val)
    except Exception:
        return "–"


def clean_txt(s):
    """Normalitza text (equips, etc.): sense accents, espais únics, minúscules."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_player_name_for_matching(name):
    """Normalitza noms traient dorsals i accents per garantir encreuaments exactes."""
    s = str(name).strip()
    s = re.sub(r"^#\d+\s*", "", s)
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("utf-8")
    return s.strip().lower()


def extract_player_number(name):
    match = re.search(r"#(\d+)", str(name))
    return f"#{match.group(1)}" if match else ""


def num_series(df, name, default=0.0):
    """Retorna la columna com a numèrica; si no existeix, una sèrie plena de 'default'."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def ensure_numeric(df, cols, default=0.0):
    for c in cols:
        df[c] = num_series(df, c, default)
    return df


def to_float(v, default=0.0):
    x = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(x) else float(x)


def safe_div(num, den):
    """Divisió vectoritzada: 0 on el denominador és 0 o NaN."""
    den = pd.Series(den)
    return (pd.Series(num) / den.where(den > 0)).fillna(0.0)


def zone_fgm(df, zone):
    """FGM d'una zona: usa la columna FGM si existeix, sinó la reconstrueix de FGA * %."""
    if f"{zone} FGM" in df.columns:
        return num_series(df, f"{zone} FGM")
    return num_series(df, f"{zone} FGA") * num_series(df, f"{zone} %") / 100.0


def add_shooting_splits(df):
    """Afegeix FGA/FGM/PPS de 2P i 3P al DataFrame (jugadors o equips)."""
    fga_2p = sum(num_series(df, f"{z} FGA") for z in ["Rim", "Paint", "MR"])
    fgm_2p = sum(zone_fgm(df, z) for z in ["Rim", "Paint", "MR"])
    fga_3p = sum(num_series(df, f"{z} FGA") for z in ["Cor3", "ATB3"])
    fgm_3p = sum(zone_fgm(df, z) for z in ["Cor3", "ATB3"])
    tot_fga = fga_2p + fga_3p

    df["FGA_2P"] = fga_2p
    df["FGA_3P"] = fga_3p
    df["PPS_Global"] = safe_div(2.0 * fgm_2p + 3.0 * fgm_3p, tot_fga)
    df["PPS_2P"] = safe_div(2.0 * fgm_2p, fga_2p)
    df["PPS_3P"] = safe_div(3.0 * fgm_3p, fga_3p)
    df["3PAr"] = safe_div(fga_3p, tot_fga) * 100.0
    df["2P%"] = safe_div(fgm_2p, fga_2p) * 100.0
    df["3P%"] = safe_div(fgm_3p, fga_3p) * 100.0
    return df


def calculate_league_average_pps(raw_games_df):
    if raw_games_df.empty:
        return 0.95
    try:
        total_attempts = sum(
            raw_games_df[c].sum() for c in [f"{z} FGA" for z in ZONES] if c in raw_games_df.columns
        )
        total_2pm = sum(
            raw_games_df[c].sum() for c in ["Rim FGM", "Paint FGM", "MR FGM"] if c in raw_games_df.columns
        )
        total_3pm = sum(
            raw_games_df[c].sum() for c in ["Cor3 FGM", "ATB3 FGM"] if c in raw_games_df.columns
        )
        total_points = 2.0 * total_2pm + 3.0 * total_3pm
        return total_points / total_attempts if total_attempts > 0 else 0.95
    except Exception:
        return 0.95


def player_mask(df, player):
    """Màscara de files de quintets on juga 'player' (compara exacte amb P1..P5)."""
    pcols = [c for c in LINEUP_PLAYER_COLS if c in df.columns]
    if pcols:
        return df[pcols].eq(player).any(axis=1)
    return df["Lineup"].astype(str).str.contains(player, regex=False, na=False)


def split_on_off(df, player):
    m = player_mask(df, player)
    return df[m], df[~m]


def get_game_chronological_sort_key(g):
    """Criteri d'ordenació cronològica per jornada/data de partits."""
    fname = g.get("filename", "") or g.get("name", "")
    m = re.search(r"(?:jornada|week|round|j)[\s_]*0*(\d+)", fname, re.IGNORECASE)
    if m:
        return (0, int(m.group(1)))
    m_date = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", fname)
    if m_date:
        return (1, m_date.group(0))
    digits = re.findall(r"\d+", fname)
    if digits:
        return (2, [int(d) for d in digits])
    return (3, fname)


# ---------------------- Estils de taules (outliers) ----------------------
def _style_outliers(column, lower_is_better, high_k, low_k):
    mean = column.mean()
    std = column.std()
    if pd.isna(std) or std == 0:
        return [""] * len(column)

    styles = []
    for val in column:
        if pd.isna(val):
            styles.append("")
        elif val > mean + high_k * std:
            styles.append(STYLE_BAD if lower_is_better else STYLE_GOOD)
        elif val < mean - low_k * std:
            styles.append(STYLE_GOOD if lower_is_better else STYLE_BAD)
        else:
            styles.append("")
    return styles


def highlight_offense_outliers(column):
    if not pd.api.types.is_numeric_dtype(column) or column.name in ["Team", "Escut", "Week"]:
        return [""] * len(column)
    return _style_outliers(column, column.name in ["DERcal", "TOV%cal"], 0.8, 0.8)


def highlight_defense_outliers(column):
    if not pd.api.types.is_numeric_dtype(column) or column.name in ["Team", "Escut", "Week"]:
        return [""] * len(column)
    return _style_outliers(column, column.name in ["OERcal", "eFG%", "ORB%cal", "FTR"], 0.8, 1.2)


def highlight_teammate_outliers(column):
    if column.name not in ["off eFG%", "def eFG%", "to%", "to%ag"]:
        return [""] * len(column)
    return _style_outliers(column, column.name in ["def eFG%", "to%"], 0.8, 0.8)


def highlight_on_off_profile_diff(df):
    style_df = pd.DataFrame("", index=df.index, columns=df.columns)
    net_idx = 2
    rules = {
        "off eFG%": True, "def eFG%": False, "to%": False, "to%ag": True,
        "RO/tram": True, "RO Ag/tram": False, "RD/tram": True, "RD Ag/tram": False,
    }
    for col, positive_is_good in rules.items():
        if col in df.columns:
            val = df.loc[net_idx, col]
            if pd.isna(val) or val == 0:
                continue
            is_good = (val > 0) if positive_is_good else (val < 0)
            style_df.loc[net_idx, col] = STYLE_GOOD if is_good else STYLE_BAD
    return style_df


def calculate_all_players_on_off_profiles(combined_df, roster_list):
    rows = []
    for player in roster_list:
        on_court, off_court = split_on_off(combined_df, player)
        if on_court.empty or off_court.empty:
            continue

        o_efg_on, d_efg_on, to_on, to_ag_on, _, _, _, _ = calculate_combo_stats_metrics(on_court)
        o_efg_off, d_efg_off, to_off, to_ag_off, _, _, _, _ = calculate_combo_stats_metrics(off_court)

        rows.append({
            "JUGADOR": player,
            "On_eFG_Off": o_efg_on, "Off_eFG_Off": o_efg_off, "Net_eFG_Off": o_efg_on - o_efg_off,
            "On_eFG_Def": d_efg_on, "Off_eFG_Def": d_efg_off, "Net_eFG_Def": d_efg_on - d_efg_off,
            "On_TO_Off": to_on, "Off_TO_Off": to_off, "Net_TO_Off": to_on - to_off,
            "On_TO_Def": to_ag_on, "Off_TO_Def": to_ag_off, "Net_TO_Def": to_ag_on - to_ag_off,
        })
    return pd.DataFrame(rows)


# ---------------------- Helpers de la fitxa de jugador ----------------------
def get_pctile(qual_df, col_name, val, invert=False):
    if col_name not in qual_df.columns or val is None or pd.isna(val):
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
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; font-size: 0.82rem;">
        <div style="color: #d1d5db; width: 165px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{label}</div>
        <div style="color: #f9fafb; font-weight: 700; width: 55px; text-align: right; font-variant-numeric: tabular-nums;">{raw_val_str}</div>
        <div style="flex-grow: 1; margin: 0 10px; background-color: #1f2937; height: 6px; border-radius: 3px; overflow: hidden;">
            <div style="background-color: #2dd4bf; width: {bar_w}%; height: 100%; border-radius: 3px;"></div>
        </div>
        <div style="color: #9ca3af; font-size: 0.75rem; font-weight: 600; width: 45px; text-align: right;">P{pct_val:.1f}</div>
    </div>
    """


def get_weighted_league_pct(players_df, zone_name):
    """% real ponderat de la lliga: sumatori FGM / sumatori FGA (ponderat per partits)."""
    gp = num_series(players_df, "GamesPlayed", 1.0)
    fga = num_series(players_df, f"{zone_name} FGA")
    pct = num_series(players_df, f"{zone_name} %")
    tot_fga = (fga * gp).sum()
    tot_fgm = (fga * pct / 100.0 * gp).sum()
    return (tot_fgm / tot_fga * 100.0) if tot_fga > 0 else 0.0


# =====================================================================
# CÀRREGA DE GAMELOGS DE JUGADORS
# =====================================================================
@st.cache_data(show_spinner=False)
def load_all_season_player_gamelogs(box_dir, pbp_dir, cache_key):
    """Carrega l'històric de partits de tots els jugadors."""
    if not box_dir or not os.path.exists(box_dir):
        return pd.DataFrame()

    raw_games_df = load_all_raw_game_boxscores(box_dir, pbp_dir, cache_key)
    file_to_week = {}
    if not raw_games_df.empty and "Game_File" in raw_games_df.columns and "Week" in raw_games_df.columns:
        file_to_week = dict(zip(raw_games_df["Game_File"], raw_games_df["Week"]))

    games = load_all_game_options(box_dir)
    records = []
    meta_pattern = "TOTAL|EQUIP|FALTE|TEAM"

    def get_clean_team_pts(df_p):
        """Suma només jugadors reals (evita duplicar punts si hi ha fila TOTAL)."""
        if df_p is None or df_p.empty or "PTS" not in df_p.columns:
            return 0
        is_meta = df_p["JUGADOR"].astype(str).str.upper().str.contains(meta_pattern)
        pts = pd.to_numeric(df_p.loc[~is_meta, "PTS"], errors="coerce").fillna(0).sum()
        if pts > 0:
            return int(round(pts))
        return int(round(pd.to_numeric(df_p["PTS"], errors="coerce").fillna(0).max()))

    for g in games:
        fname = g.get("filename", "") or g.get("name", "")

        week_str = file_to_week.get(fname, "") or file_to_week.get(g.get("name", ""), "")
        m_j = re.search(r"\d+", str(week_str))
        if not m_j:
            m_j = re.search(r"(?:jornada|week|round|j)[\s_]*0*(\d+)", fname, re.IGNORECASE)

        round_num = int(m_j.group(1) if (m_j and m_j.re.groups) else m_j.group(0)) if m_j else 999
        round_label = f"J{round_num}" if round_num != 999 else ""

        try:
            _, (t1_name, t1_p), (t2_name, t2_p) = parse_boxscore(g["path"])
        except Exception as e:
            st.warning(f"No s'ha pogut llegir el boxscore '{fname}': {e}")
            continue

        score_t1 = get_clean_team_pts(t1_p)
        score_t2 = get_clean_team_pts(t2_p)

        for df_p, t_name, opp_name, my_sc, opp_sc in [
            (t1_p, t1_name, t2_name, score_t1, score_t2),
            (t2_p, t2_name, t1_name, score_t2, score_t1),
        ]:
            if df_p is None or df_p.empty or "JUGADOR" not in df_p.columns:
                continue

            w_l = "W" if my_sc >= opp_sc else "L"
            res_text = f"{my_sc}-{opp_sc} {w_l}"

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
                    "PTS": to_float(r.get("PTS", 0.0)),
                    "EFI": to_float(r.get("EFI", 0.0)),
                    "TIME": str(r.get("TIME", "00:00")),
                    "2PM": to_float(r.get("2PM", 0.0)),
                    "2PA": to_float(r.get("2PA", 0.0)),
                    "3PM": to_float(r.get("3PM", 0.0)),
                    "3PA": to_float(r.get("3PA", 0.0)),
                    "FTM": to_float(r.get("FTM", 0.0)),
                    "FTA": to_float(r.get("FTA", 0.0)),
                })

    return pd.DataFrame(records)


# =====================================================================
# SIDEBAR
# =====================================================================
copa_logo_path = "copa_catalunya.png"
if os.path.exists(copa_logo_path):
    with open(copa_logo_path, "rb") as image_file:
        encoded_logo = base64.b64encode(image_file.read()).decode()

    st.sidebar.markdown(
        f'''
        <div style="display: flex; justify-content: center; align-items: center; margin-top: 15px; margin-bottom: 25px; width: 100%;">
            <img src="data:image/png;base64,{encoded_logo}" style="max-height: 90px; max-width: 190px; object-fit: contain; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
        </div>
        ''',
        unsafe_allow_html=True,
    )
else:
    st.sidebar.title("Dashboard Copa Catalunya")

seasons = get_available_seasons(RAW_DIR)

if not seasons:
    st.sidebar.error("Crea una carpeta de temporada (ex: 'Copa_2025_2026') dins de data/raw/")
    st.info("Estructura de carpetes: `data/raw/NOM_DE_LA_TEMPORADA/pbp/`, etc.")
    st.stop()

selected_season = st.sidebar.selectbox("Selecciona la Temporada", seasons)

# Resolució de rutes (insensible a majúscules, amb fallback a l'arrel)
PBP_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "pbp")
if not PBP_DIR or not os.path.exists(PBP_DIR):
    PBP_DIR = resolve_path_case_insensitive(RAW_DIR, "pbp")

BOX_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "boxscores")
if not BOX_DIR or not os.path.exists(BOX_DIR):
    BOX_DIR = resolve_path_case_insensitive(RAW_DIR, "boxscores")

AGG_FILE = resolve_path_case_insensitive(RAW_DIR, selected_season, "aggregate", "aggregate_season_latest.xlsx")
if not AGG_FILE or not os.path.exists(AGG_FILE):
    AGG_FILE = resolve_path_case_insensitive(RAW_DIR, "aggregate", "aggregate_season_latest.xlsx")

HAS_BOX = bool(BOX_DIR) and os.path.exists(BOX_DIR)
HAS_PBP_DIR = bool(PBP_DIR) and os.path.exists(PBP_DIR)
HAS_AGG = bool(AGG_FILE) and os.path.exists(AGG_FILE)

view = st.sidebar.radio(
    "Visualitzacions",
    ["Anàlisi Partits", "Acumulats Lliga", "Scouting Jugadors", "Scouting Equips"],
)

with st.sidebar.container(key="sidebar_bottom"):
    st.markdown(
        '''
        <div style="font-size: 0.75rem; color: rgba(128, 128, 128, 0.55); text-align: left; line-height: 1.4; font-family: sans-serif;">
            Dades FCBQ<br>
            Víctor Solanes 2026
        </div>
        ''',
        unsafe_allow_html=True,
    )

st.sidebar.markdown(
    """
    <style>
    div[data-element-idx="sidebar_bottom"] { position: absolute; bottom: 20px; }
    .st-key-sidebar_bottom { position: absolute; bottom: 20px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# =====================================================================
# VISTA 1: ANÀLISI PARTITS
# =====================================================================
if view == "Anàlisi Partits":
    st.title(f"Analitzador de Partits ({selected_season.replace('_', ' ')})")

    if not HAS_BOX:
        st.info("No s'ha trobat la carpeta de boxscores. Comprova els noms de directori.")
        st.stop()

    games = load_all_game_options(BOX_DIR)
    if not games:
        st.info("No s'han carregat partits. Afegeix els teus fitxers de boxscore/pbp de la setmana.")
        st.stop()

    if HAS_AGG:
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

    if not filtered_games:
        st.info(f"No s'han trobat partits per a {filter_team_game}.")
        st.stop()

    selected_game = st.selectbox("2. Selecciona el Partit", filtered_games, format_func=lambda g: g["name"])

    team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])

    pbp_path = find_best_matching_pbp(t1_name, t2_name, PBP_DIR, selected_game["filename"])
    has_pbp = pbp_path is not None and os.path.exists(pbp_path)

    pbp_df_param = None
    pbp_df, lineups_df = None, None
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
            st.markdown(get_logo_html_centered(logo_path_t1), unsafe_allow_html=True)
    with col_lgB:
        logo_path_t2 = get_team_logo_path(t2_name, selected_season)
        if logo_path_t2:
            st.markdown(get_logo_html_centered(logo_path_t2), unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    t1_stats = team_summary.iloc[0]
    t2_stats = team_summary.iloc[1]

    with col1:
        st.metric(label="Possessions (Ritme/Pace)", value=f"{t1_stats['POSScal']:.1f}")
    with col2:
        st.metric(label=f"Ràting d'Atac / Defensa - {t1_name}",
                  value=f"{t1_stats['OERcal']:.1f} / {t1_stats['DERcal']:.1f}")
    with col3:
        st.metric(label=f"Ràting d'Atac / Defensa - {t2_name}",
                  value=f"{t2_stats['OERcal']:.1f} / {t2_stats['DERcal']:.1f}")
    with col4:
        st.metric(label="Durada del Partit", value=f"{estimated_game_mins} min",
                  help="Durada d'aquest partit basada en els períodes jugats.")

    st.subheader("Comparació dels 4 Factors")
    factors = ["eFG%", "TOV%cal", "ORB%cal", "FTR"]
    factor_ranges = {
        "eFG%": [0.0, 80.0], "TOV%cal": [0.0, 40.0], "ORB%cal": [0.0, 60.0], "FTR": [0.0, 0.80],
    }

    col_f1, col_f2 = st.columns(2)
    for i, factor in enumerate(factors):
        with (col_f1 if i % 2 == 0 else col_f2):
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=[t1_name, t2_name],
                x=[t1_stats[factor], t2_stats[factor]],
                orientation="h",
                marker_color=[CB_BLUE, CB_ORANGE],
                text=[f"{t1_stats[factor]:.2f}", f"{t2_stats[factor]:.2f}"],
                textposition="inside",
            ))
            fig.update_layout(
                title=f"Factor: {factor}",
                height=200,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, range=factor_ranges[factor]),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Perfils de Rendiment dels Jugadors")

    stat_view = st.radio(
        "Selecciona la vista d'estadístiques",
        ["Estadístiques Estàndard", "Mètriques Avançades", "Sèries per Zona de Tir"],
        horizontal=True,
    )

    standard_cols = ["JUGADOR", "TIME", "PTS", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA",
                     "ORB", "DRB", "AS", "STL", "BLK", "TO", "F", "F+"]
    advanced_cols = ["JUGADOR", "TIME", "EFI", "USG%cal", "eFG%", "TS%", "FTR", "TO%cal",
                     "PTS/PLAYcal", "TOpts", "2CPts"]
    zone_cols = ["JUGADOR", "TIME", "Rim FGM", "Rim FGA", "Rim %", "Paint FGM", "Paint FGA", "Paint %",
                 "MR FGM", "MR FGA", "MR %", "Cor3 FGM", "Cor3 FGA", "Cor3 %",
                 "ATB3 FGM", "ATB3 FGA", "ATB3 %"]

    team_tab1, team_tab2 = st.tabs([t1_name, t2_name])

    for tab, players_df in zip([team_tab1, team_tab2], [t1_players, t2_players]):
        with tab:
            wanted = {"Estadístiques Estàndard": standard_cols,
                      "Mètriques Avançades": advanced_cols}.get(stat_view, zone_cols)
            selected_cols = [c for c in wanted if c in players_df.columns]

            col_config = {"JUGADOR": st.column_config.TextColumn("JUGADOR", width=260)}
            for col in selected_cols:
                if col == "JUGADOR":
                    continue
                if col == "TIME":
                    col_config[col] = st.column_config.TextColumn(col, width=65)
                else:
                    col_config[col] = st.column_config.NumberColumn(col, width=55)

            st.dataframe(
                players_df[selected_cols].style.format(precision=2),
                use_container_width=False,
                column_config=col_config,
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
                    players_list = sorted(
                        list(pbp_df[pbp_df["Shot_Team"] == selected_team]["Player"].dropna().unique())
                    )
                shot_player_sel = st.selectbox("Filtra els llançaments per jugador", ["Tots"] + players_list)
                shot_player = "All" if shot_player_sel == "Tots" else shot_player_sel

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
                league_pps=league_pps_val,
            )

            col_map1, col_map2 = st.columns(2)
            with col_map1:
                st.plotly_chart(fig_vol, use_container_width=True)
            with col_map2:
                st.plotly_chart(fig_pps, use_container_width=True)

            st.markdown("---")
            st.write("Quarter/Time Event Feed")
            st.dataframe(pbp_df[["quarter", "time", "text"]].dropna().head(100),
                         height=500, use_container_width=True)

        with lineup_tab:
            selected_lineup_team = st.selectbox("Filtra els quintets per equip",
                                                ["Tots els equips", t1_name, t2_name])
            filtered_lineups = lineups_df.copy()

            if selected_lineup_team != "Tots els equips":
                team_col = None
                for col in lineups_df.columns:
                    as_str = lineups_df[col].astype(str)
                    if as_str.str.contains(t1_name, regex=False, na=False).any() or \
                            as_str.str.contains(t2_name, regex=False, na=False).any():
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
                if col_str in LINEUP_PLAYER_COLS:
                    lineup_col_config[col] = st.column_config.TextColumn(col, width="medium")
                elif col_str == "Lineup":
                    lineup_col_config[col] = st.column_config.TextColumn(col, width="large")
                elif col in pct_cols:
                    lineup_col_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width="small")
                elif pd.api.types.is_numeric_dtype(filtered_lineups[col]):
                    lineup_col_config[col] = st.column_config.NumberColumn(col, width="small")
                else:
                    lineup_col_config[col] = st.column_config.TextColumn(col, width="small")

            st.write("Rendiment dels Quintets a la Pista")
            st.dataframe(filtered_lineups, use_container_width=False,
                         column_config=lineup_col_config, hide_index=True)
    else:
        st.warning("No s'ha trobat cap fitxer Play-By-Play per a aquest partit. "
                   "S'ha fet una cerca aproximada però no hi ha coincidències.")


# =====================================================================
# VISTA 2: ACUMULATS LLIGA
# =====================================================================
elif view == "Acumulats Lliga":
    st.title(f"Tendències de la Lliga ({selected_season.replace('_', ' ')})")

    if not HAS_BOX:
        st.info("No s'ha trobat la carpeta de boxscores. Comprova els noms de directori.")
        st.stop()

    pbp_cache_key = get_dir_cache_key(BOX_DIR)
    raw_games_df = load_all_raw_game_boxscores(BOX_DIR, PBP_DIR, pbp_cache_key)

    if raw_games_df.empty:
        st.info("No s'han trobat dades de boxscores per calcular les tendències de la lliga.")
        st.stop()

    st.subheader("Filtre dinàmic de partits de la lliga")

    missing_week_games = raw_games_df[raw_games_df["Week"] == "Altres / Sense Jornada"]
    if not missing_week_games.empty:
        st.warning("⚠️ S'han trobat partits que no s'han pogut assignar a cap jornada. "
                   "Revisa el desplegable inferior d'avisos.")
        with st.expander("Avisos de fitxers (Alguns partits de la carpeta no tenen la Jornada assignada)"):
            st.write("Els següents partits no han trobat el seu fitxer Play-By-Play corresponent o no s'ha "
                     "pogut extreure la jornada, pel que s'han assignat a 'Altres / Sense Jornada':")
            st.dataframe(missing_week_games[["Game_Name", "Game_File"]].drop_duplicates(),
                         use_container_width=True, hide_index=True)

    select_all_weeks = st.checkbox("Inclou Totes les Jornades de la temporada", value=True)

    week_options = sorted(
        list(raw_games_df["Week"].dropna().unique()),
        key=lambda w: ([int(s) for s in re.findall(r"\d+", str(w))] or [10**6], str(w)),
    )

    if select_all_weeks:
        selected_weeks = week_options
        st.info("Totes les jornades estan incloses en els càlculs de lliga.")
    else:
        selected_weeks = st.multiselect(
            "Selecciona les Jornades a incloure de forma manual (desmarca per excloure'ls rànquings)",
            week_options,
            default=week_options,
        )

    if not selected_weeks:
        st.warning("Selecciona almenys una jornada de lliga per calcular les tendències dinàmiques.")
        st.stop()

    filtered_raw_off = raw_games_df[raw_games_df["Week"].isin(selected_weeks)].copy()

    # Construcció de les dades defensives (el que concedeix el rival en cada partit)
    shared_cols = ["POSScal", "eFG%", "TOV%cal", "ORB%cal", "FTR"]
    zone_raw_cols = [f"{z} {k}" for z in ZONES for k in ("FGM", "FGA")]
    all_def_rows = []
    for _, group in raw_games_df.groupby("Game_File"):
        if len(group) != 2:
            continue
        rows = [group.iloc[0], group.iloc[1]]
        for me, opp in [(rows[0], rows[1]), (rows[1], rows[0])]:
            d = {
                "Team": me["Team"], "Game_Name": me["Game_Name"],
                "Game_File": me["Game_File"], "Week": me["Week"],
                "OERcal": me["DERcal"], "DERcal": me["OERcal"], "POSScal": me["POSScal"],
            }
            for c in ["eFG%", "TOV%cal", "ORB%cal", "FTR"] + zone_raw_cols:
                d[c] = opp.get(c, np.nan)
            all_def_rows.append(d)

    raw_defense_df = pd.DataFrame(all_def_rows)
    if raw_defense_df.empty:
        filtered_raw_def = pd.DataFrame(columns=["Team", "Week"])
    else:
        filtered_raw_def = raw_defense_df[raw_defense_df["Week"].isin(selected_weeks)].copy()

    agg_cols = ["POSScal", "OERcal", "DERcal", "eFG%", "TOV%cal", "ORB%cal", "FTR"] + zone_raw_cols
    ensure_numeric(filtered_raw_off, [c for c in agg_cols if c in filtered_raw_off.columns])
    ensure_numeric(filtered_raw_def, [c for c in agg_cols if c in filtered_raw_def.columns])

    offense_df = filtered_raw_off.groupby("Team").agg(
        {c: "mean" for c in agg_cols if c in filtered_raw_off.columns}).reset_index()
    defense_df = filtered_raw_def.groupby("Team").agg(
        {c: "mean" for c in agg_cols if c in filtered_raw_def.columns}).reset_index()

    for df_t in [offense_df, defense_df]:
        for zone in ZONES:
            fgm_c, fga_c, pct_c = f"{zone} FGM", f"{zone} FGA", f"{zone} %"
            if fgm_c in df_t.columns and fga_c in df_t.columns:
                df_t[pct_c] = safe_div(df_t[fgm_c], df_t[fga_c]) * 100.0

    offense_df["Escut"] = offense_df["Team"].apply(lambda t: get_team_logo_base64_url(t, selected_season))
    defense_df["Escut"] = defense_df["Team"].apply(lambda t: get_team_logo_base64_url(t, selected_season))

    view_off_cols = ["Escut"] + [c for c in offense_df.columns if c != "Escut"]
    view_def_cols = ["Escut"] + [c for c in defense_df.columns if c != "Escut"]

    league_col_config = {
        "Escut": st.column_config.ImageColumn("Escut", width="small"),
        "Team": st.column_config.TextColumn("Team", width=260),
    }
    for col in offense_df.columns:
        if col not in ["Team", "Escut"]:
            league_col_config[col] = st.column_config.NumberColumn(col, width=65)

    tab_off, tab_def, tab_chart, tab_team_profile = st.tabs(
        ["Dades Equips", "Dades Rivals", "Gràfic de Dispersió", "Perfil de Tir de l'Equip"]
    )

    with tab_off:
        st.write("Mètriques Ofensives dels Equips recalculades en viu (Dades Equips)")
        styled_offense = (offense_df[view_off_cols].sort_values("OERcal", ascending=False)
                          .style.format(precision=2).apply(highlight_offense_outliers))
        st.dataframe(styled_offense, use_container_width=False, height=600,
                     column_config=league_col_config)

    with tab_def:
        st.write("Mètriques Defensives dels Rivals recalculades en viu (Dades Rivals)")
        styled_defense = (defense_df[view_def_cols].sort_values("DERcal", ascending=True)
                          .style.format(precision=2).apply(highlight_defense_outliers))
        st.dataframe(styled_defense, use_container_width=False, height=600,
                     column_config=league_col_config)

    with tab_chart:
        st.write("Gràfic d'Anàlisi Dinàmica de la Lliga (Exclou partits, destaca rivals i veu els canvis en directe)")

        league_df = offense_df.merge(defense_df, on="Team", suffixes=("_Off", "_Def"))

        st.write("### Opcions de personalització del gràfic")
        teams_list_scat = sorted(list(league_df["Team"].unique()))

        highlight_sel = st.multiselect(
            "Selecciona un o varis equips per destacar al gràfic (es pintaran en taronja i es faran més grans)",
            teams_list_scat,
            default=[],
        )

        if highlight_sel:
            is_hl = league_df["Team"].isin(highlight_sel)
            league_df["Visual_Group"] = np.where(is_hl, "Destacat", "Resta de la Lliga")
            league_df["Visual_Size"] = np.where(is_hl, 16, 10)
            color_map = {"Destacat": CB_ORANGE, "Resta de la Lliga": "rgba(180, 180, 180, 0.55)"}
        else:
            league_df["Visual_Group"] = "Equips de la Lliga"
            league_df["Visual_Size"] = 12
            color_map = {"Equips de la Lliga": CB_BLUE}

        x_labels = {
            "OERcal_Off": "Ràting Ofensiu (OER)",
            "eFG%_Off": "eFG% Ofensiu",
            "TOV%cal_Off": "Ràtio de Pèrdues Ofensiu (TO%)",
            "ORB%cal_Off": "Rebot Ofensiu % (ORB%)",
            "FTR_Off": "Ràtio de Tirs Lliures Ofensiu (FTR)",
        }
        y_labels = {
            "DERcal_Off": "Ràting Defensiu (DER)",
            "eFG%_Def": "eFG% Defensiu (Rival eFG%)",
            "TOV%cal_Def": "Ràtio de Pèrdues Defensiu (Rival TO%)",
            "ORB%cal_Def": "Opponent Rebot Ofensiu % (Rival ORB%)",
            "FTR_Def": "Ràtio de Tirs Lliures Defensiu (Rival FTR)",
        }

        col_scat1, col_scat2 = st.columns(2)
        with col_scat1:
            x_metric = st.selectbox("Eix X (Mètrica Ofensiva)", list(x_labels.keys()),
                                    format_func=lambda x: x_labels[x], key="league_x_selector")
        with col_scat2:
            y_metric = st.selectbox("Eix Y (Mètrica Defensiva)", list(y_labels.keys()),
                                    format_func=lambda y: y_labels[y], key="league_y_selector")

        mean_x = league_df[x_metric].mean()
        mean_y = league_df[y_metric].mean()
        max_dev_x = (league_df[x_metric] - mean_x).abs().max()
        max_dev_y = (league_df[y_metric] - mean_y).abs().max()

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
                "FTR_Def": "FTR Defensiu",
            },
        )
        fig_scat.update_traces(textposition="top center", textfont=dict(size=10, color="#555555"))
        fig_scat.update_layout(height=650, xaxis=dict(range=x_range), yaxis=dict(range=y_range))
        fig_scat.add_vline(x=mean_x, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Atac")
        fig_scat.add_hline(y=mean_y, line_dash="dash", line_color=CB_ORANGE, annotation_text="Mitjana Def")
        st.plotly_chart(fig_scat, use_container_width=True)

    with tab_team_profile:
        scout_teams = sorted(list(offense_df["Team"].unique()))
        selected_profile_team = st.selectbox("Selecciona l'Equip per analitzar el seu Perfil de Tir", scout_teams)

        league_pps_val = calculate_league_average_pps(filtered_raw_off)

        st.subheader("📊 Perfil de Tir Ofensiu (Atac)")
        fig_vol_seasonal, fig_pps_seasonal = draw_team_seasonal_zone_charts(
            offense_df, selected_profile_team, league_pps_val)

        col_prof1, col_prof2 = st.columns(2)
        with col_prof1:
            st.plotly_chart(fig_vol_seasonal, use_container_width=True)
        with col_prof2:
            st.plotly_chart(fig_pps_seasonal, use_container_width=True)

        st.markdown("---")
        st.subheader("📊 Perfil de Tir Defensiu (Defensa - Permès als Rivals)")
        st.write("Estudia quins llançaments concedeix aquest equip: els gràfics següents mostren el volum "
                 "i l'eficiència (PPS) de tir dels rivals quan juguen contra ells.")

        fig_vol_def, fig_pps_def = draw_team_seasonal_zone_charts(
            defense_df, selected_profile_team, league_pps_val)

        col_def1, col_def2 = st.columns(2)
        with col_def1:
            fig_vol_def.update_layout(title=f"Volum de Tirs Concedits de Mitjana - {selected_profile_team}")
            st.plotly_chart(fig_vol_def, use_container_width=True)
        with col_def2:
            fig_pps_def.update_layout(title=f"Eficiència de Tir Concedida (PPS) - {selected_profile_team}")
            st.plotly_chart(fig_pps_def, use_container_width=True)


# =====================================================================
# VISTA 3: SCOUTING JUGADORS
# =====================================================================
elif view == "Scouting Jugadors":
    st.title(f"Scouting de Jugadors ({selected_season.replace('_', ' ')})")

    if not HAS_AGG:
        st.info("No s'han trobat acumulats de lliga. Comprova els fitxers d'acumulats de la temporada.")
        st.stop()

    offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
    master_players = master_players.copy()

    # Neteja de tipus
    ensure_numeric(master_players, ["PTS", "eFG%", "TS%", "FGA", "EFI", "USG%cal", "TO%cal", "FTR", "F+"])
    master_players["GamesPlayed"] = num_series(master_players, "GamesPlayed", 1.0)
    ensure_numeric(master_players, [f"{z} FGA" for z in ZONES] + [f"{z} %" for z in ZONES])
    # FT% es manté com a NaN si no existeix (no s'inventen valors)
    if "FT%" in master_players.columns:
        master_players["FT%"] = pd.to_numeric(master_players["FT%"], errors="coerce")

    master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
    master_players = add_shooting_splits(master_players)

    # Gamelogs de la temporada (en memòria cau)
    pbp_cache_key = get_dir_cache_key(BOX_DIR) if HAS_BOX else None
    season_logs_df = (load_all_season_player_gamelogs(BOX_DIR, PBP_DIR, pbp_cache_key)
                      if HAS_BOX else pd.DataFrame())

    # Selector superior del jugador
    scout_p_teams = ["Tots els equips"] + sorted(list(master_players["Team"].dropna().unique()))
    col_s1, col_s2 = st.columns([1.5, 2.5])
    with col_s1:
        filter_team_card = st.selectbox("Filtra jugadors per equip", scout_p_teams, index=0)
    with col_s2:
        if filter_team_card != "Tots els equips":
            roster_avail = sorted(list(master_players[master_players["Team"] == filter_team_card]["JUGADOR"].unique()))
        else:
            roster_avail = sorted(list(master_players["JUGADOR"].unique()))
        selected_player_card = st.selectbox("Selecciona el jugador per obrir la Fitxa d'Scouting",
                                            roster_avail, index=0)

    p_row = master_players[master_players["JUGADOR"] == selected_player_card].iloc[0]
    p_team = p_row["Team"]
    p_gp = int(p_row["GamesPlayed"])
    p_min = p_row.get("TIME", "00:00")
    p_num = extract_player_number(selected_player_card)
    p_clean_display = re.sub(r"^#\d+\s+", "", selected_player_card).strip()

    p_clean_target = clean_player_name_for_matching(selected_player_card)
    if not season_logs_df.empty:
        player_logs = season_logs_df[season_logs_df["Clean_Name"] == p_clean_target].copy()
        player_logs = player_logs.sort_values(by=["Round_Num", "Filename"]).reset_index(drop=True)
    else:
        player_logs = pd.DataFrame()

    tab_eybl, tab_global_table = st.tabs(
        ["👤 Fitxa d'Scouting Individual (Perfil EYBL)", "📋 Rànquings & Taula de Lliga"]
    )

    with tab_eybl:
        # --- Capçalera d'identitat ---
        team_logo_url = get_team_logo_base64_url(p_team, selected_season)
        logo_card = ""
        if team_logo_url:
            logo_card = f"""
            <div style="background-color: #ffffff; border-radius: 8px; padding: 4px 10px; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.3); height: 56px; min-width: 65px;">
                <img src="{team_logo_url}" style="max-height: 46px; max-width: 70px; object-fit: contain;">
            </div>
            """

        header_html = f"""
        <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 16px;">
                <div style="background: linear-gradient(135deg, #1f77b4 0%, #0d3b66 100%); color: white; width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.35rem; font-weight: 800; border: 2px solid rgba(255,255,255,0.2);">
                    {p_num if p_num else "🏀"}
                </div>
                <div>
                    <h1 style="margin: 0; color: #f9fafb; font-size: 2.1rem; font-weight: 800; line-height: 1.1;">{p_clean_display}</h1>
                    <div style="color: #9ca3af; font-size: 1.05rem; font-weight: 500; margin-top: 4px;">{p_team} &nbsp;•&nbsp; Copa Catalunya</div>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 18px;">
                <div style="text-align: right;">
                    <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800; line-height: 1.1;">{p_gp} <span style="font-size: 1.1rem; color: #9ca3af;">GP</span></div>
                    <div style="color: #9ca3af; font-size: 0.95rem; font-weight: 500; margin-top: 4px;">{p_min} <span style="font-size: 0.8rem;">MIN/G</span></div>
                </div>
                {logo_card}
            </div>
        </div>
        """
        render_html(header_html)

        # Mitjanes i màxims de lliga (una sola vegada)
        league_avg_dict = {
            "Rim_FGA": master_players["Rim FGA"].mean() or 0.0,
            "Paint_FGA": master_players["Paint FGA"].mean() or 0.0,
            "MR_FGA": master_players["MR FGA"].mean() or 0.0,
            "Cor3_FGA": master_players["Cor3 FGA"].mean() or 0.0,
            "ATB3_FGA": master_players["ATB3 FGA"].mean() or 0.0,
            "Rim_Pct": get_weighted_league_pct(master_players, "Rim"),
            "Paint_Pct": get_weighted_league_pct(master_players, "Paint"),
            "MR_Pct": get_weighted_league_pct(master_players, "MR"),
            "Cor3_Pct": get_weighted_league_pct(master_players, "Cor3"),
            "ATB3_Pct": get_weighted_league_pct(master_players, "ATB3"),
        }
        league_max_dict = {z: master_players[f"{z} FGA"].max() or 1.0 for z in ZONES}

        # PPS del jugador (ja calculats a master_players)
        pps_global_val = float(p_row["PPS_Global"])
        pps_2p_val = float(p_row["PPS_2P"])
        pps_3p_val = float(p_row["PPS_3P"])

        # Tirs i taxes: logs reals si n'hi ha, sinó reconstrucció per zones
        if not player_logs.empty and player_logs["3PA"].sum() > 0:
            tot_2pm = int(player_logs["2PM"].sum())
            tot_2pa = int(player_logs["2PA"].sum())
            tot_3pm = int(player_logs["3PM"].sum())
            tot_3pa = int(player_logs["3PA"].sum())
            tot_ftm = int(player_logs["FTM"].sum())
            tot_fta = int(player_logs["FTA"].sum())
            pct_ft = (tot_ftm / tot_fta * 100.0) if tot_fta > 0 else np.nan
        else:
            fga_2p_pg = float(p_row["FGA_2P"])
            fga_3p_pg = float(p_row["FGA_3P"])
            tot_2pa = int(round(fga_2p_pg * p_gp))
            tot_2pm = int(round(fga_2p_pg * p_row["2P%"] / 100.0 * p_gp))
            tot_3pa = int(round(fga_3p_pg * p_gp))
            tot_3pm = int(round(fga_3p_pg * p_row["3P%"] / 100.0 * p_gp))
            pct_ft = to_float(p_row.get("FT%", np.nan), np.nan)
            tot_ftm = int(round(to_float(p_row.get("FTM", 0)) * p_gp))
            tot_fta = int(round(to_float(p_row.get("FTA", 0)) * p_gp))

        pct_2p = (tot_2pm / tot_2pa * 100.0) if tot_2pa > 0 else 0.0
        pct_3p = (tot_3pm / tot_3pa * 100.0) if tot_3pa > 0 else 0.0
        tot_fga_cnt = tot_2pa + tot_3pa
        p_3par = (tot_3pa / tot_fga_cnt * 100.0) if tot_fga_cnt > 0 else 0.0
        ft_count_str = f"{tot_ftm}/{tot_fta}" if tot_fta > 0 else ""
        ft_pct_str = safe_fmt("{:.1f}%", pct_ft)

        col_left, col_right = st.columns([1.05, 1.15])

        # ========== COLUMNA ESQUERRA ==========
        with col_left:
            render_html(f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Season production</div>
                <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 8px;">Per game</div>
                <div style="display: flex; justify-content: space-between; align-items: center; text-align: center;">
                    <div>
                        <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800;">{p_row['PTS']:.1f}</div>
                        <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">PTS/G</div>
                    </div>
                    <div>
                        <div style="color: #2dd4bf; font-size: 1.8rem; font-weight: 800;">{pps_global_val:.2f}</div>
                        <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">PPS (Pts/Tir)</div>
                    </div>
                    <div>
                        <div style="color: #f9fafb; font-size: 1.8rem; font-weight: 800;">{p_row['FGA']:.1f}</div>
                        <div style="color: #9ca3af; font-size: 0.72rem; font-weight: 600;">FGA/G</div>
                    </div>
                </div>
            </div>
            """)

            render_html("""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px; margin-bottom: 14px;">
                <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Perfil de Tir (Radars)</div>
                <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 6px;">Volum & Eficiència per zones vs Lliga</div>
            </div>
            """)

            fig_v_rad, fig_e_rad = draw_player_radar_charts(p_row, league_avg_dict, league_max_dict)
            radar_choice = st.radio("Tipus de radar", ["Eficiència (%)", "Volum (FGA)"],
                                    horizontal=True, label_visibility="collapsed")
            st.plotly_chart(fig_e_rad if radar_choice == "Eficiència (%)" else fig_v_rad,
                            use_container_width=True)

            # Scoring by game
            high_pts = player_logs["PTS"].max() if not player_logs.empty else p_row["PTS"]
            render_html(f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px 14px 4px 14px; margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Scoring by game</div>
                        <div style="color: #6b7280; font-size: 0.75rem;">Season &bull; {len(player_logs)} partits registrats</div>
                    </div>
                    <div style="color: #2dd4bf; font-size: 0.82rem; font-weight: 700;">High {high_pts:.0f} pts</div>
                </div>
            </div>
            """)

            if not player_logs.empty:
                player_logs["Game_Label"] = [
                    r["Round_Str"] if r.get("Round_Str") else f"P{i + 1}"
                    for i, (_, r) in enumerate(player_logs.iterrows())
                ]
                fig_sc_trend = px.bar(
                    player_logs, x="Game_Label", y="PTS",
                    hover_data={"Game_Label": True, "Opponent": True, "PTS": True, "TIME": True},
                    color_discrete_sequence=["#2dd4bf"],
                )
                fig_sc_trend.update_layout(
                    height=145,
                    margin=dict(l=10, r=10, t=10, b=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, title=None, tickfont=dict(size=9, color="#9ca3af")),
                    yaxis=dict(showgrid=True, gridcolor="#1f2937", title=None,
                               tickfont=dict(size=9, color="#9ca3af")),
                )
                st.plotly_chart(fig_sc_trend, use_container_width=True, config={"displayModeBar": False})

            # Box shooting & rates
            render_html(f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 24px;">
                <div style="color: #9ca3af; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">Box shooting & rates</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; text-align: center;">
                    <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                        <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">2P%</div>
                        <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{pct_2p:.1f}%</div>
                        <div style="color: #9ca3af; font-size: 0.65rem;">{tot_2pm}/{tot_2pa}</div>
                    </div>
                    <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                        <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">3P%</div>
                        <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{pct_3p:.1f}%</div>
                        <div style="color: #9ca3af; font-size: 0.65rem;">{tot_3pm}/{tot_3pa}</div>
                    </div>
                    <div style="background-color: #1f2937; padding: 8px; border-radius: 6px;">
                        <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">FT%</div>
                        <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{ft_pct_str}</div>
                        <div style="color: #9ca3af; font-size: 0.65rem;">{ft_count_str}</div>
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
                        <div style="color: #9ca3af; font-size: 0.7rem; font-weight: 600;">3PAr</div>
                        <div style="color: #f9fafb; font-size: 1.15rem; font-weight: 800;">{p_3par:.1f}%</div>
                        <div style="color: #9ca3af; font-size: 0.65rem;">Freq Triple</div>
                    </div>
                </div>
            </div>
            """)

        # ========== COLUMNA DRETA ==========
        with col_right:
            qual_df = master_players[master_players["GamesPlayed"] >= 3].copy()
            if len(qual_df) < 5:
                qual_df = master_players.copy()

            def pct_of(col, val):
                return get_pctile(qual_df, col, val)

            adv_bars_html = f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; margin-bottom: 14px;">
                <div style="color: #f9fafb; font-size: 1.05rem; font-weight: 700; margin-bottom: 2px;">Advanced scouting profile</div>
                <div style="color: #6b7280; font-size: 0.75rem; margin-bottom: 10px;">Percentils Copa Catalunya &bull; GP &ge; 3</div>

                <div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 6px; margin-bottom: 6px;'>CREACIÓ & VOLUM DE TIR</div>
                {render_eybl_bar("Punts / Partit", f"{p_row['PTS']:.1f}", pct_of("PTS", p_row["PTS"]))}
                {render_eybl_bar("Tirs Intentats (FGA)", f"{p_row['FGA']:.1f}", pct_of("FGA", p_row["FGA"]))}
                {render_eybl_bar("Ràtio Triples (3PAr)", f"{p_3par:.1f}%", pct_of("3PAr", p_3par))}
                {render_eybl_bar("Minuts / Partit", f"{p_row['MinPerGame']:.1f}'", pct_of("MinPerGame", p_row["MinPerGame"]))}

                <div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 14px; margin-bottom: 6px;'>EFICIÈNCIA & ENCERT</div>
                {render_eybl_bar("Tir Efectiu (eFG%)", f"{p_row['eFG%']:.1f}%", pct_of("eFG%", p_row["eFG%"]))}
                {render_eybl_bar("True Shooting (TS%)", f"{p_row['TS%']:.1f}%", pct_of("TS%", p_row["TS%"]))}
                {render_eybl_bar("Encert Triple (3P%)", f"{pct_3p:.1f}%", pct_of("3P%", pct_3p))}
                {render_eybl_bar("Tirs Lliures (FT%)", ft_pct_str, pct_of("FT%", pct_ft))}
                {render_eybl_bar("Forçar Tirs Lliures (FTR)", f"{p_row['FTR']:.2f}", pct_of("FTR", p_row["FTR"]))}

                <div style='color: #9ca3af; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 14px; margin-bottom: 6px;'>PUNTS PER TIR (PPS)</div>
                {render_eybl_bar("PPS Global (Pts/Tir)", f"{pps_global_val:.2f}", pct_of("PPS_Global", pps_global_val))}
                {render_eybl_bar("PPS Tir de 2 (2P)", f"{pps_2p_val:.2f}", pct_of("PPS_2P", pps_2p_val))}
                {render_eybl_bar("PPS Tir de 3 (3P)", f"{pps_3p_val:.2f}", pct_of("PPS_3P", pps_3p_val))}
            </div>
            """
            render_html(adv_bars_html)

            # Shot distribution
            zones_scout = [
                ("Rim", "Cèrcol (Rim)"),
                ("Paint", "Pintura (Paint)"),
                ("MR", "Mitja Distància (MR)"),
                ("Cor3", "Corner 3"),
                ("ATB3", "Top / Wing 3 (ATB)"),
            ]
            rows_html = ""
            for z_id, z_name in zones_scout:
                z_pct = to_float(p_row.get(f"{z_id} %", 0))
                z_fga = to_float(p_row.get(f"{z_id} FGA", 0))
                z_lg_pct = league_avg_dict[f"{z_id}_Pct"]
                delta = z_pct - z_lg_pct
                delta_color = "#2dd4bf" if delta >= 0 else "#f87171"
                delta_sign = "+" if delta > 0 else ""
                rows_html += f"""
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; margin-bottom: 7px;">
                    <div style="width: 140px; color: #e5e7eb;">
                        <div style="font-weight: 600;">{z_name}</div>
                        <div style="font-size: 0.7rem; color: #9ca3af;">{z_fga:.1f} FGA/p</div>
                    </div>
                    <div style="width: 45px; text-align: right; color: #ffffff; font-weight: 700;">{z_pct:.1f}</div>
                    <div style="width: 50px; text-align: right; color: #9ca3af;">{z_lg_pct:.1f}</div>
                    <div style="width: 45px; text-align: right; color: {delta_color}; font-weight: 700;">{delta_sign}{delta:.1f}</div>
                </div>
                """

            render_html(f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                <div style="color: #f9fafb; font-size: 0.95rem; font-weight: 700; margin-bottom: 2px;">Shot distribution</div>
                <div style="color: #9ca3af; font-size: 0.75rem; margin-bottom: 10px;">FG% vs Copa Cat &bull; delta in pp</div>
                <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #9ca3af; font-weight: 700; border-bottom: 1px solid #374151; padding-bottom: 4px; margin-bottom: 8px;">
                    <div style="width: 140px;">Zone / FG</div>
                    <div style="width: 45px; text-align: right;">FG%</div>
                    <div style="width: 50px; text-align: right;">COPA</div>
                    <div style="width: 45px; text-align: right;">Δ pp</div>
                </div>
                {rows_html}
            </div>
            """)

            # Recent box scores
            recent_rows_html = ""
            if not player_logs.empty:
                recent_5 = player_logs.tail(5).iloc[::-1]
                for _, r_log in recent_5.iterrows():
                    fgm_tot = int(r_log["2PM"] + r_log["3PM"])
                    fga_tot = int(r_log["2PA"] + r_log["3PA"])
                    r_label = f"[{r_log['Round_Str']}] " if r_log.get("Round_Str") else ""
                    score_info = f" &bull; {r_log['Score_Result']}" if r_log.get("Score_Result") else ""
                    pts_fg_game = r_log["2PM"] * 2.0 + r_log["3PM"] * 3.0
                    pps_game = (pts_fg_game / fga_tot) if fga_tot > 0 else 0.0

                    recent_rows_html += f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2937; padding: 7px 0;">
                        <div>
                            <div style="color: #ffffff; font-size: 0.82rem; font-weight: 700;">{r_label}vs {r_log['Opponent']}</div>
                            <div style="color: #9ca3af; font-size: 0.72rem;">{r_log['TIME']}{score_info} &bull; FG: {fgm_tot}/{fga_tot}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="color: #2dd4bf; font-size: 0.95rem; font-weight: 800;">{r_log['PTS']:.0f} <span style="font-size: 0.75rem; color: #9ca3af;">PTS</span></div>
                            <div style="color: #9ca3af; font-size: 0.72rem;">{pps_game:.2f} PPS</div>
                        </div>
                    </div>
                    """
            else:
                recent_rows_html = "<div style='color: #9ca3af; font-size: 0.8rem;'>Sense registre de partits individuals.</div>"

            render_html(f"""
            <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 24px;">
                <div style="color: #f9fafb; font-size: 0.95rem; font-weight: 700; margin-bottom: 2px;">Recent box scores</div>
                <div style="color: #9ca3af; font-size: 0.75rem; margin-bottom: 10px;">PTS / PPS / MIN &bull; Últims partits jugats</div>
                {recent_rows_html}
            </div>
            """)

    # --- Pestanya 2: rànquings i taula global ---
    with tab_global_table:
        st.write("Motor de cerca i rànquings oficials de jugadors de la lliga:")

        col_tf1, col_tf2 = st.columns([1.5, 2.5])
        with col_tf1:
            if filter_team_card != "Tots els equips":
                filter_by_team = st.checkbox(f"Filtrar només per l'equip seleccionat ({filter_team_card})", value=True)
            else:
                filter_by_team = False
        with col_tf2:
            filter_by_player = st.checkbox(f"Mostrar només a {p_clean_display}", value=False)

        max_gp = max(int(master_players["GamesPlayed"].max() or 1), 2)
        max_fga = max(float(master_players["FGA"].max() or 1.0), 1.0)
        max_min = max(float(master_players["MinPerGame"].max() or 1.0), 1.0)

        col_filt1, col_filt2, col_filt3, col_filt4 = st.columns(4)
        with col_filt1:
            sort_metric_sel = st.selectbox(
                "Ordenar per:",
                ["Punts (PTS)", "Punts per Tir (PPS)", "Tir Efectiu (eFG%)", "2P%", "3P%",
                 "Ràtio Triples (3PAr)", "Partits Jugats", "Minuts/p"],
                index=0,
            )
        with col_filt2:
            min_games = st.slider("Mínim de partits", 1, max_gp, min(3, max_gp))
        with col_filt3:
            min_fga = st.slider("Mínim FGA/p (Volum)", 0.0, max_fga, min(2.0, max_fga), step=0.5)
        with col_filt4:
            min_mins = st.slider("Mínim min/p", 0.0, max_min, min(8.0, max_min), step=1.0)

        sort_map = {
            "Punts (PTS)": "PTS",
            "Punts per Tir (PPS)": "PPS_Global",
            "Tir Efectiu (eFG%)": "eFG%",
            "2P%": "2P%",
            "3P%": "3P%",
            "Ràtio Triples (3PAr)": "3PAr",
            "Partits Jugats": "GamesPlayed",
            "Minuts/p": "MinPerGame",
        }

        table_df = master_players.copy()
        if filter_by_team and filter_team_card != "Tots els equips":
            table_df = table_df[table_df["Team"] == filter_team_card]
        if filter_by_player:
            table_df = table_df[table_df["JUGADOR"] == selected_player_card]

        filtered_table = table_df[
            (table_df["GamesPlayed"] >= min_games)
            & (table_df["FGA"] >= min_fga)
            & (table_df["MinPerGame"] >= min_mins)
        ].sort_values(sort_map[sort_metric_sel], ascending=False)

        view_cols_all = [
            "JUGADOR", "Team", "GamesPlayed", "TIME", "PTS", "FGA", "2P%", "3P%", "FT%",
            "eFG%", "TS%", "PPS_Global", "3PAr",
            "Rim FGA", "Rim %", "Paint FGA", "Paint %", "MR FGA", "MR %",
            "Cor3 FGA", "Cor3 %", "ATB3 FGA", "ATB3 %",
        ]
        view_cols = [c for c in view_cols_all if c in filtered_table.columns]

        player_index_config = {
            "JUGADOR": st.column_config.TextColumn("JUGADOR", width=220),
            "Team": st.column_config.TextColumn("Equip", width=160),
            "GamesPlayed": st.column_config.NumberColumn("GP", width=50),
            "TIME": st.column_config.TextColumn("MIN", width=65),
            "PTS": st.column_config.NumberColumn("PTS", width=55),
            "FGA": st.column_config.NumberColumn("FGA", width=55),
            "2P%": st.column_config.NumberColumn("2P%", format="%.1f%%", width=65),
            "3P%": st.column_config.NumberColumn("3P%", format="%.1f%%", width=65),
            "FT%": st.column_config.NumberColumn("FT%", format="%.1f%%", width=65),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.1f%%", width=65),
            "TS%": st.column_config.NumberColumn("TS%", format="%.1f%%", width=65),
            "PPS_Global": st.column_config.NumberColumn("PPS", format="%.2f", width=60),
            "3PAr": st.column_config.NumberColumn("3PAr", format="%.1f%%", width=65),
        }
        for z in ZONES:
            player_index_config[f"{z} FGA"] = st.column_config.NumberColumn(f"{z} FGA", width=55)
            player_index_config[f"{z} %"] = st.column_config.NumberColumn(f"{z} %", format="%.1f%%", width=60)

        fmt_map = {
            "TIME": "{}", "FGA": "{:.1f}", "PTS": "{:.1f}",
            "2P%": "{:.1f}%", "3P%": "{:.1f}%", "FT%": "{:.1f}%",
            "eFG%": "{:.2f}%", "TS%": "{:.2f}%", "PPS_Global": "{:.2f}", "3PAr": "{:.1f}%",
        }
        for z in ZONES:
            fmt_map[f"{z} FGA"] = "{:.1f}"
            fmt_map[f"{z} %"] = "{:.1f}%"
        fmt_map = {k: v for k, v in fmt_map.items() if k in view_cols}

        def highlight_selected_player_row(row):
            if row["JUGADOR"] == selected_player_card:
                return ["background-color: rgba(45, 212, 191, 0.18); font-weight: bold;"] * len(row)
            return [""] * len(row)

        st.dataframe(
            filtered_table[view_cols].style.format(fmt_map, na_rep="–").apply(highlight_selected_player_row, axis=1),
            use_container_width=False,
            column_config=player_index_config,
            height=650,
        )


# =====================================================================
# VISTA 4: SCOUTING EQUIPS
# =====================================================================
elif view == "Scouting Equips":
    st.title(f"Scouting Equips ({selected_season.replace('_', ' ')})")

    if not HAS_AGG:
        st.info("No s'ha trobat el fitxer d'acumulats de lliga. Afegeix 'aggregate_season_latest.xlsx' a la seva carpeta.")
        st.stop()

    offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)

    teams_list = sorted(list(offense_df["Team"].unique()))
    col_tA, col_tB = st.columns(2)
    with col_tA:
        team_A = st.selectbox("Selecciona l'Equip A", teams_list, index=0)
    with col_tB:
        team_B = st.selectbox("Selecciona l'Equip B", teams_list, index=min(1, len(teams_list) - 1))

    if team_A == team_B:
        st.warning("Selecciona dos equips diferents per poder fer la comparativa de scouting.")
        st.stop()

    col_logo_A, col_vs, col_logo_B = st.columns([1, 0.5, 1])
    with col_logo_A:
        logo_path_A = get_team_logo_path(team_A, selected_season)
        if logo_path_A:
            st.markdown(get_logo_html_centered(logo_path_A, 100, 140), unsafe_allow_html=True)
        else:
            st.subheader(team_A)
    with col_vs:
        st.markdown("<h2 style='text-align: center; line-height: 100px; color: gray;'>VS</h2>",
                    unsafe_allow_html=True)
    with col_logo_B:
        logo_path_B = get_team_logo_path(team_B, selected_season)
        if logo_path_B:
            st.markdown(get_logo_html_centered(logo_path_B, 100, 140), unsafe_allow_html=True)
        else:
            st.subheader(team_B)

    st.markdown("---")
    st.subheader("Comparativa de Rànquings i Eficiència de l'Equip")

    off_ranks = offense_df.copy()
    def_ranks = defense_df.copy()

    for df_t in [off_ranks, def_ranks]:
        add_shooting_splits(df_t)
        df_t["%T2"] = df_t["2P%"]
        df_t["%T3"] = df_t["3P%"]
        if "FT%" in df_t.columns:
            df_t["%T1"] = pd.to_numeric(df_t["FT%"], errors="coerce")
        elif "FT_Pct" in df_t.columns:
            df_t["%T1"] = pd.to_numeric(df_t["FT_Pct"], errors="coerce")
        else:
            df_t["%T1"] = np.nan  # no s'inventen valors
        df_t["Us_tir_2"] = df_t["FGA_2P"]
        df_t["Us_Tir_3"] = df_t["FGA_3P"]
        df_t["Pts_T2"] = df_t["PPS_2P"]
        df_t["Pts_T3"] = df_t["PPS_3P"]

    # Rànquings ofensius (més alt = millor, excepte TOV)
    off_rank_spec = {
        "OER_Rank": ("OERcal", False), "eFG_Rank": ("eFG%", False), "ORB_Rank": ("ORB%cal", False),
        "FTR_Rank": ("FTR", False), "Pace_Rank": ("POSScal", False), "TOV_Rank": ("TOV%cal", True),
        "T1_Rank": ("%T1", False), "T2_Rank": ("%T2", False), "T3_Rank": ("%T3", False),
        "Us_T2_Rank": ("Us_tir_2", False), "Us_T3_Rank": ("Us_Tir_3", False),
        "Pts_T2_Rank": ("Pts_T2", False), "Pts_T3_Rank": ("Pts_T3", False),
    }
    for rank_col, (src, asc) in off_rank_spec.items():
        off_ranks[rank_col] = off_ranks[src].rank(ascending=asc, method="min")

    # Rànquings defensius (més baix = millor, excepte TOV forçades)
    def_rank_spec = {
        "DER_Rank": ("OERcal", True), "eFG_Def_Rank": ("eFG%", True), "TOV_Def_Rank": ("TOV%cal", False),
        "ORB_Def_Rank": ("ORB%cal", True), "FTR_Def_Rank": ("FTR", True),
        "Pts_T2_Def_Rank": ("Pts_T2", True), "Pts_T3_Def_Rank": ("Pts_T3", True),
    }
    for rank_col, (src, asc) in def_rank_spec.items():
        def_ranks[rank_col] = def_ranks[src].rank(ascending=asc, method="min")

    def get_team_scout_stats(team_name):
        t_off = off_ranks[off_ranks["Team"] == team_name].iloc[0]
        t_def = def_ranks[def_ranks["Team"] == team_name].iloc[0]
        return {
            "OER": (t_off["OERcal"], safe_rank(t_off["OER_Rank"])),
            "DER": (t_def["OERcal"], safe_rank(t_def["DER_Rank"])),
            "Pace": (t_off["POSScal"], safe_rank(t_off["Pace_Rank"])),
            "eFG": (t_off["eFG%"], safe_rank(t_off["eFG_Rank"])),
            "TOV": (t_off["TOV%cal"], safe_rank(t_off["TOV_Rank"])),
            "ORB": (t_off["ORB%cal"], safe_rank(t_off["ORB_Rank"])),
            "FTR": (t_off["FTR"], safe_rank(t_off["FTR_Rank"])),
            "eFG_Def": (t_def["eFG%"], safe_rank(t_def["eFG_Def_Rank"])),
            "TOV_Def": (t_def["TOV%cal"], safe_rank(t_def["TOV_Def_Rank"])),
            "ORB_Def": (t_def["ORB%cal"], safe_rank(t_def["ORB_Def_Rank"])),
            "FTR_Def": (t_def["FTR"], safe_rank(t_def["FTR_Def_Rank"])),
            "T1": (t_off["%T1"], safe_rank(t_off["T1_Rank"])),
            "T2": (t_off["%T2"], safe_rank(t_off["T2_Rank"])),
            "T3": (t_off["%T3"], safe_rank(t_off["T3_Rank"])),
            "Us_T2": (t_off["Us_tir_2"], safe_rank(t_off["Us_T2_Rank"])),
            "Us_T3": (t_off["Us_Tir_3"], safe_rank(t_off["Us_T3_Rank"])),
            "Pts_T2": (t_off["Pts_T2"], safe_rank(t_off["Pts_T2_Rank"])),
            "Pts_T3": (t_off["Pts_T3"], safe_rank(t_off["Pts_T3_Rank"])),
            "Pts_T2_Def": (t_def["Pts_T2"], safe_rank(t_def["Pts_T2_Def_Rank"])),
            "Pts_T3_Def": (t_def["Pts_T3"], safe_rank(t_def["Pts_T3_Def_Rank"])),
        }

    stats_A = get_team_scout_stats(team_A)
    stats_B = get_team_scout_stats(team_B)

    DEF_KEYS = ["DER", "eFG_Def", "TOV_Def", "ORB_Def", "FTR_Def", "Pts_T2_Def", "Pts_T3_Def"]
    LOWER_BETTER_KEYS = ["DER", "TOV", "eFG_Def", "ORB_Def", "FTR_Def", "Pts_T2_Def", "Pts_T3_Def"]
    STRENGTH_COL_MAP = {
        "OER": "OERcal", "DER": "OERcal", "Pace": "POSScal",
        "eFG": "eFG%", "TOV": "TOV%cal", "ORB": "ORB%cal", "FTR": "FTR",
        "eFG_Def": "eFG%", "TOV_Def": "TOV%cal", "ORB_Def": "ORB%cal", "FTR_Def": "FTR",
        "T1": "%T1", "T2": "%T2", "T3": "%T3",
        "Us_T2": "Us_tir_2", "Us_T3": "Us_Tir_3",
        "Pts_T2": "Pts_T2", "Pts_T3": "Pts_T3",
        "Pts_T2_Def": "Pts_T2", "Pts_T3_Def": "Pts_T3",
    }

    def get_normalized_strength(key, val):
        df_target = def_ranks if key in DEF_KEYS else off_ranks
        col_name = STRENGTH_COL_MAP[key]

        if val is None or pd.isna(val):
            return 0.0
        min_v = float(df_target[col_name].min())
        max_v = float(df_target[col_name].max())
        if pd.isna(min_v) or pd.isna(max_v):
            return 0.0
        if max_v == min_v:
            return 0.5

        if key in LOWER_BETTER_KEYS:
            norm = (max_v - val) / (max_v - min_v)
        else:
            norm = (val - min_v) / (max_v - min_v)
        return max(0.0, min(1.0, float(norm)))

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
        ("Pts_T3_Def", "PPS permesos de 3P (Pts T3 riv)", "{:.2f} PPS"),
    ]

    mirror_data = []
    for key, name, fmt in metrics_mapping:
        val_A, rank_A = stats_A[key]
        val_B, rank_B = stats_B[key]
        mirror_data.append({
            "Fortalesa (A)": get_normalized_strength(key, val_A),
            f"Rànquing ({team_A})": f"{cat_rank(rank_A)} ({safe_fmt(fmt, val_A)})",
            "Mètrica de Lliga": name,
            f"Rànquing ({team_B})": f"{cat_rank(rank_B)} ({safe_fmt(fmt, val_B)})",
            "Fortalesa (B)": get_normalized_strength(key, val_B),
        })

    mirror_df = pd.DataFrame(mirror_data)
    mirror_col_config = {
        "Fortalesa (A)": st.column_config.ProgressColumn("Fortalesa", min_value=0.0, max_value=1.0, width="medium"),
        f"Rànquing ({team_A})": st.column_config.TextColumn(f"Rànquing ({team_A})", width=150),
        "Mètrica de Lliga": st.column_config.TextColumn("Mètrica de Lliga", width=300),
        f"Rànquing ({team_B})": st.column_config.TextColumn(f"Rànquing ({team_B})", width=150),
        "Fortalesa (B)": st.column_config.ProgressColumn("Fortalesa", min_value=0.0, max_value=1.0, width="medium"),
    }
    st.dataframe(mirror_df, use_container_width=False, column_config=mirror_col_config,
                 hide_index=True, height=760)

    # ---------------- Ràdars tàctics ----------------
    st.markdown("---")
    st.subheader("📊 Ràdars Tàctics de l'Atac vs Defensa (4 Factors)")
    st.write("Analitza la identitat tàctica d'ambdós rivals: la línia blava representa la força de fons "
             "ofensiva i la taronja la seva fortalesa defensiva en el rànquing de lliga.")

    OFF_RADAR_KEYS = ["OER", "eFG", "TOV", "ORB", "FTR"]
    DEF_RADAR_KEYS = ["DER", "eFG_Def", "TOV_Def", "ORB_Def", "FTR_Def"]

    def radar_strengths(stats, keys):
        return [get_normalized_strength(k, stats[k][0]) for k in keys]

    fig_rad_A = draw_scouting_4f_radar_chart(
        team_A, radar_strengths(stats_A, OFF_RADAR_KEYS), radar_strengths(stats_A, DEF_RADAR_KEYS))
    fig_rad_B = draw_scouting_4f_radar_chart(
        team_B, radar_strengths(stats_B, OFF_RADAR_KEYS), radar_strengths(stats_B, DEF_RADAR_KEYS))

    col_scout_rad1, col_scout_rad2 = st.columns(2)
    with col_scout_rad1:
        st.plotly_chart(fig_rad_A, use_container_width=True)
    with col_scout_rad2:
        st.plotly_chart(fig_rad_B, use_container_width=True)

    # ---------------- Anàlisi per jugador ----------------
    st.markdown("---")
    st.subheader("Anàlisi Comparatiu per Jugador (Volum i PPS per Trams)")

    def calculate_player_splits_scout(team_name):
        if master_players is None or master_players.empty:
            return pd.DataFrame()

        clean_target = clean_txt(team_name)

        # 1. Filtre exacte
        mask_exact = master_players["Team"].astype(str).str.strip().str.lower() == str(team_name).strip().lower()
        df_players = master_players[mask_exact].copy()

        # 2. Filtre flexible (tolerant a patrocinadors: Argentona / Ibersofas...)
        if df_players.empty and "Team" in master_players.columns:
            def match_team_flexible(val):
                c = clean_txt(val)
                if not c:
                    return False
                if c == clean_target or c in clean_target or clean_target in c:
                    return True
                for kw in ["argentona", "ibersofas", "palamos", "gaudi", "sardenya", "bas",
                           "martinenc", "salt", "aecam", "castellet"]:
                    if kw in clean_target and kw in c:
                        return True
                return False

            df_players = master_players[master_players["Team"].apply(match_team_flexible)].copy()

        if df_players.empty:
            return pd.DataFrame()

        # Normalitza el nom de la columna del jugador
        for col in ["JUGADOR", "Jugador", "Player", "Nom", "Name"]:
            if col in df_players.columns:
                df_players["JUGADOR"] = df_players[col]
                break

        df_players["GamesPlayed"] = num_series(df_players, "GamesPlayed", 0.0)
        add_shooting_splits(df_players)

        scout_cols = ["JUGADOR", "GamesPlayed", "FGA_2P", "PPS_2P", "FGA_3P", "PPS_3P"]
        scout_cols_avail = [c for c in scout_cols if c in df_players.columns]
        return df_players[scout_cols_avail].sort_values("FGA_2P", ascending=False).reset_index(drop=True)

    players_A_scout = calculate_player_splits_scout(team_A)
    players_B_scout = calculate_player_splits_scout(team_B)

    scout_tab1, scout_tab2 = st.tabs([f"Jugadors - {team_A}", f"Jugadors - {team_B}"])

    scout_col_config = {"JUGADOR": st.column_config.TextColumn("JUGADOR", width=260)}
    scout_format = {"FGA_2P": "{:.1f}", "PPS_2P": "{:.2f}", "FGA_3P": "{:.1f}", "PPS_3P": "{:.2f}"}

    for tab, scout_df, t_name in [(scout_tab1, players_A_scout, team_A), (scout_tab2, players_B_scout, team_B)]:
        with tab:
            st.write(f"Volum de tirs i PPS per a llançaments de 2 i 3 punts de {t_name}")
            if not scout_df.empty:
                st.dataframe(scout_df.style.format(scout_format), use_container_width=False,
                             column_config=scout_col_config, hide_index=True)
            else:
                st.info(f"No hi ha dades individuals disponibles per a {t_name}.")

    # ---------------- Quintets, rotació i parelles ----------------
    st.markdown("---")
    st.subheader("Anàlisi Avançat de Quintets, Rotació i Parelles")
    st.write("Estudia les rotacions de qualsevol dels dos equips: revisa el rendiment dels seus quintets, "
             "l'impacte net de cada jugador de la plantilla (On-Off) o la coincidència de parelles.")

    selected_scout_lineup_team = st.radio("Selecciona l'equip a analitzar:", [team_A, team_B], horizontal=True)

    if not HAS_PBP_DIR:
        st.info("No s'ha trobat la carpeta de Play-by-Play d'aquesta temporada.")
        st.stop()

    pbp_cache_key = get_dir_cache_key(PBP_DIR)
    agg_lineups, combined_df = load_and_aggregate_season_lineups(
        PBP_DIR, selected_scout_lineup_team, pbp_cache_key)

    if agg_lineups.empty or combined_df.empty:
        st.info(f"No s'han trobat dades de Play-by-Play per a {selected_scout_lineup_team} en aquesta temporada.")
        st.stop()

    st.write(f"#### 🏀 Quintets Acumulats de **{selected_scout_lineup_team}**")
    lineup_cols = [
        "P1", "P2", "P3", "P4", "P5", "Lineup", "PTS_For", "PTS_Agn", "+/-",
        "RO_For", "RD_For", "RO_Agn", "RD_Agn",
        "2PA_For", "2P%_For", "2PA_Agn", "2P%_Agn",
        "3PA_For", "3P%_For", "3PA_Agn", "3P%_Agn",
        "TOV_For", "TOV_Agn",
    ]
    selected_lineup_cols = [c for c in lineup_cols if c in agg_lineups.columns]
    pct_cols = [c for c in selected_lineup_cols if "%" in c]

    lineup_col_config = {}
    for col in selected_lineup_cols:
        if col in LINEUP_PLAYER_COLS:
            lineup_col_config[col] = st.column_config.TextColumn(col, width="medium")
        elif col == "Lineup":
            lineup_col_config[col] = st.column_config.TextColumn(col, width="large")
        elif col in pct_cols:
            lineup_col_config[col] = st.column_config.NumberColumn(col, format="%.1f%%", width="small")
        else:
            lineup_col_config[col] = st.column_config.NumberColumn(col, width="small")

    st.dataframe(agg_lineups[selected_lineup_cols], use_container_width=False,
                 column_config=lineup_col_config, hide_index=True)

    # ---------------- Mapa d'impacte On-Off ----------------
    st.write("")
    st.write(f"#### 📊 Mapa d'Impacte On-Off vs. Eficiència de la Plantilla - {selected_scout_lineup_team}")
    st.write("Aquest gràfic analitza l'impacte net de cada jugador de rotació: l'**Eix X** mostra la "
             "millora/gir de l'equip a pista (On - Off) i l'**Eix Y** mostra l'eficiència absoluta quan el "
             "jugador juga. El quadrant superior dret sempre representa el màxim impacte positiu.")

    roster = set()
    for c in LINEUP_PLAYER_COLS:
        if c in combined_df.columns:
            roster.update(combined_df[c].dropna().unique())
    roster_list = sorted(list(roster))

    if not roster_list:
        st.info("No s'ha pogut extreure la plantilla dels quintets.")
        st.stop()

    roster_on_off_df = calculate_all_players_on_off_profiles(combined_df, roster_list)

    if not roster_on_off_df.empty:
        col_met1, _ = st.columns([2, 2])
        with col_met1:
            scout_metric = st.selectbox(
                "Mètrica d'Impacte per al Gràfic de Dispersió",
                ["eFG% Ofensiu (Atac)", "eFG% Defensiu (Rival)", "Pèrdues % (TO%)",
                 "Pèrdues % Rivals Forçades (TO% Rival)"],
                key="scout_team_onoff_metric",
            )

        metric_map = {
            "eFG% Ofensiu (Atac)": ("Net_eFG_Off", "On_eFG_Off", "eFG% Atac a Pista", "Millora eFG% Atac (On-Off)"),
            "eFG% Defensiu (Rival)": ("Net_eFG_Def", "On_eFG_Def", "eFG% Defensiu a Pista", "Millora eFG% Defensiu (On-Off)"),
            "Pèrdues % (TO%)": ("Net_TO_Off", "On_TO_Off", "Pèrdues % a Pista", "Millora TO% (On-Off)"),
            "Pèrdues % Rivals Forçades (TO% Rival)": ("Net_TO_Def", "On_TO_Def", "Pèrdues Rivals a Pista", "Millora TO% Rival (On-Off)"),
        }
        x_col, y_col, y_label, x_label = metric_map[scout_metric]

        fig_scat_onoff = px.scatter(
            roster_on_off_df,
            x=x_col, y=y_col,
            hover_name="JUGADOR", text="JUGADOR",
            title=f"Mapa d'Impacte On-Off - {selected_scout_lineup_team} ({scout_metric})",
            labels={x_col: x_label, y_col: y_label},
            color_discrete_sequence=[CB_BLUE],
        )
        fig_scat_onoff.update_traces(textposition="top center", textfont=dict(size=10, color="#444444"))
        fig_scat_onoff.add_vline(x=0.0, line_dash="dash", line_color=CB_ORANGE,
                                 annotation_text="Llindar Canvi Zero", annotation_position="top right")

        true_avg_y = roster_on_off_df[y_col].mean()
        avg_line_label = f"Mitjana Plantilla a Pista ({true_avg_y:.2f}%)"
        try:
            if x_col == "Net_eFG_Off":
                true_avg_y = float(offense_df[offense_df["Team"] == selected_scout_lineup_team]["eFG%"].iloc[0])
                avg_line_label = f"Mitjana Atac {selected_scout_lineup_team} ({true_avg_y:.2f}%)"
            elif x_col == "Net_eFG_Def":
                true_avg_y = float(defense_df[defense_df["Team"] == selected_scout_lineup_team]["eFG%"].iloc[0])
                avg_line_label = f"Mitjana Def {selected_scout_lineup_team} ({true_avg_y:.2f}%)"
        except IndexError:
            pass

        fig_scat_onoff.add_hline(y=true_avg_y, line_dash="dot", line_color="gray",
                                 annotation_text=avg_line_label, annotation_position="top left")

        if x_col in ["Net_eFG_Def", "Net_TO_Off"]:
            fig_scat_onoff.update_xaxes(autorange="reversed")
        if y_col in ["On_eFG_Def", "On_TO_Off"]:
            fig_scat_onoff.update_yaxes(autorange="reversed")

        st.plotly_chart(fig_scat_onoff, use_container_width=True)

    # ---------------- Parelles i coincidència ----------------
    st.write("")
    st.write(f"#### 👥 Anàlisi de Parelles i Coincidència de **{selected_scout_lineup_team}**")

    col_pX, col_pY = st.columns(2)
    with col_pX:
        player_X = st.selectbox("Selecciona el Jugador A (Principal)", roster_list, index=0, key="scout_player_x")
    with col_pY:
        roster_with_none = ["Cap (Només Jugador A)"] + [p for p in roster_list if p != player_X]
        player_Y = st.selectbox("Selecciona el Jugador B (Opcional)", roster_with_none, index=0, key="scout_player_y")

    if player_Y == "Cap (Només Jugador A)":
        on_court, off_court = split_on_off(combined_df, player_X)

        st.write(f"Rendiment global d'On/Off per a **{player_X}**:")
        col_on, col_off, col_net = st.columns(3)

        plus_on = on_court["+/-"].sum() if not on_court.empty else 0.0
        plus_off = off_court["+/-"].sum() if not off_court.empty else 0.0
        net_impact = plus_on - plus_off

        with col_on:
            st.metric(
                label=f"A Pista ({player_X})", value=f"{plus_on:+.1f}",
                help=f"Equip jugant amb el Jugador A a pista. Punts a favor: {on_court['PTS_For'].sum():.0f}, "
                     f"Punts en contra: {on_court['PTS_Agn'].sum():.0f}")
        with col_off:
            st.metric(
                label="A la Banqueta (Off-Court)", value=f"{plus_off:+.1f}",
                help=f"Equip jugant sense el Jugador A a pista. Punts a favor: {off_court['PTS_For'].sum():.0f}, "
                     f"Punts en contra: {off_court['PTS_Agn'].sum():.0f}")
        with col_net:
            st.metric(
                label="Impacte NET (On-Off)", value=f"{net_impact:+.1f}",
                help=f"Diferencial net de l'equip amb el jugador a pista vs. a la banqueta. "
                     f"Càlcul: {plus_on:+.1f} - ({plus_off:+.1f}) = {net_impact:+.1f}")

        target_clean_name = clean_player_name_for_matching(player_X)
        scout_player_rows = master_players[
            master_players["JUGADOR"].apply(clean_player_name_for_matching) == target_clean_name]

        if not scout_player_rows.empty:
            scout_player_row = scout_player_rows.iloc[0]
            avg_time = scout_player_row.get("TIME", "00:00")
            games_played_val = int(to_float(scout_player_row.get("GamesPlayed", 1), 1))
        else:
            avg_time = "00:00"
            games_played_val = 0

        trams_on = len(on_court)
        trams_off = len(off_court)

        o_efg_on, d_efg_on, to_on, to_ag_on, ro_on, ro_ag_on, rd_on, rd_ag_on = \
            calculate_combo_stats_metrics(on_court)
        o_efg_off, d_efg_off, to_off, to_ag_off, ro_off, ro_ag_off, rd_off, rd_ag_off = \
            calculate_combo_stats_metrics(off_court)

        def per_tram(total, n):
            return total / n if n > 0 else 0.0

        ro_on_s, ro_off_s = per_tram(ro_on, trams_on), per_tram(ro_off, trams_off)
        ro_ag_on_s, ro_ag_off_s = per_tram(ro_ag_on, trams_on), per_tram(ro_ag_off, trams_off)
        rd_on_s, rd_off_s = per_tram(rd_on, trams_on), per_tram(rd_off, trams_off)
        rd_ag_on_s, rd_ag_off_s = per_tram(rd_ag_on, trams_on), per_tram(rd_ag_off, trams_off)

        profile_rows = [
            {
                "Estat": f"A Pista ({player_X})", "Trams": trams_on,
                "off eFG%": o_efg_on, "def eFG%": d_efg_on, "to%": to_on, "to%ag": to_ag_on,
                "RO/tram": ro_on_s, "RO Ag/tram": ro_ag_on_s, "RD/tram": rd_on_s, "RD Ag/tram": rd_ag_on_s,
            },
            {
                "Estat": "A la Banqueta (Off)", "Trams": trams_off,
                "off eFG%": o_efg_off, "def eFG%": d_efg_off, "to%": to_off, "to%ag": to_ag_off,
                "RO/tram": ro_off_s, "RO Ag/tram": ro_ag_off_s, "RD/tram": rd_off_s, "RD Ag/tram": rd_ag_off_s,
            },
            {
                "Estat": "Diferencial (NET)", "Trams": trams_on - trams_off,
                "off eFG%": o_efg_on - o_efg_off, "def eFG%": d_efg_on - d_efg_off,
                "to%": to_on - to_off, "to%ag": to_ag_on - to_ag_off,
                "RO/tram": ro_on_s - ro_off_s, "RO Ag/tram": ro_ag_on_s - ro_ag_off_s,
                "RD/tram": rd_on_s - rd_off_s, "RD Ag/tram": rd_ag_on_s - rd_ag_off_s,
            },
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
            "RD Ag/tram": st.column_config.NumberColumn("RD riv/tram", format="%.2f", width=95),
        }

        st.write("")
        st.write(f"📊 **Perfil de Rendiment Detallat d'On/Off per a {player_X}:**")
        st.caption(f"⏱️ **Minuts de mitjana per partit:** {avg_time} | "
                   f"🏆 **Partits jugats total:** {games_played_val} | 🔄 **Trams jugats:** {trams_on}")
        st.dataframe(
            profile_df.style.apply(highlight_on_off_profile_diff, axis=None),
            use_container_width=False, column_config=profile_config, hide_index=True,
        )

        # Companys de pista
        st.write("")
        teammate_stats = []
        for teammate in roster_list:
            if teammate == player_X:
                continue

            both_on_raw = combined_df[player_mask(combined_df, player_X) & player_mask(combined_df, teammate)]
            if both_on_raw.empty:
                continue

            o_efg, d_efg, to_p, to_pa, ro, ro_ag, rd, rd_ag = calculate_combo_stats_metrics(both_on_raw)

            if "Week" in both_on_raw.columns and "Rival" in both_on_raw.columns:
                game_ids = both_on_raw["Week"].astype(str) + "_" + both_on_raw["Rival"].astype(str)
                partits_junts = int(game_ids.nunique())
            elif "Rival" in both_on_raw.columns:
                partits_junts = int(both_on_raw["Rival"].nunique())
            else:
                partits_junts = 1

            teammate_stats.append({
                "Company": teammate,
                "+/- Acumulat": both_on_raw["+/-"].sum(),
                "Partits": partits_junts,
                "Trams": int(len(both_on_raw)),
                "off eFG%": o_efg, "def eFG%": d_efg, "to%": to_p, "to%ag": to_pa,
                "ro": ro, "ro Ag": ro_ag, "rd": rd, "rd ag": rd_ag,
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
                "rd ag": st.column_config.NumberColumn("RD riv", width=65),
            }
            with col_best:
                st.write(f"👍 **Millors companyies per a {player_X}**")
                st.dataframe(teammate_df.head(3).style.apply(highlight_teammate_outliers),
                             use_container_width=False, hide_index=True, column_config=t_config)
            with col_worst:
                st.write(f"👎 **Pitjors companyies per a {player_X}**")
                st.dataframe(
                    teammate_df.tail(3).sort_values("+/- Acumulat", ascending=True)
                    .style.apply(highlight_teammate_outliers),
                    use_container_width=False, hide_index=True, column_config=t_config)
    else:
        mask_X = player_mask(combined_df, player_X)
        mask_Y = player_mask(combined_df, player_Y)

        combos = [
            ("Junts a Pista", combined_df[mask_X & mask_Y],
             "Ambdós jugadors jugant junts."),
            (f"Només {player_X}", combined_df[mask_X & ~mask_Y],
             "Jugador X jugant sense Jugador Y."),
            (f"Només {player_Y}", combined_df[~mask_X & mask_Y],
             "Jugador Y jugant sense Jugador X."),
            ("Ambdós a la Banqueta", combined_df[~mask_X & ~mask_Y],
             "Cap dels dos jugadors a pista."),
        ]

        st.write(f"Rendiment de l'equip segons la presència de **{player_X}** i **{player_Y}**:")
        for col, (label, sub_df, desc) in zip(st.columns(4), combos):
            with col:
                pm = sub_df["+/-"].sum() if not sub_df.empty else 0.0
                st.metric(
                    label=label, value=f"{pm:+.1f}",
                    help=f"{desc} Punts a favor: {sub_df['PTS_For'].sum():.0f}, "
                         f"Punts en contra: {sub_df['PTS_Agn'].sum():.0f}")