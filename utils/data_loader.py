import pandas as pd
import numpy as np
import glob
import os
import re
import datetime
import streamlit as st
import base64

def resolve_path_case_insensitive(base_dir, *subdirs_and_file):
    """
    Traverses directories case-insensitively on Linux platforms.
    For example: resolve_path_case_insensitive("data/raw", "Copa_2025_2026", "aggregate", "aggregate_season_latest.xlsx")
    """
    current_path = base_dir
    if not os.path.exists(current_path):
        return None
        
    for part in subdirs_and_file:
        try:
            entries = os.listdir(current_path)
        except OSError:
            return None
            
        # Match case-insensitively
        match = None
        for entry in entries:
            if entry.lower() == part.lower():
                match = entry
                break
        
        if match is None:
            # Fallback if looking for a file: check if any xlsx exists in this directory
            if part.endswith(".xlsx"):
                xlsx_files = [e for e in entries if e.lower().endswith(".xlsx")]
                if xlsx_files:
                    match = xlsx_files[0]
                else:
                    return None
            else:
                return None
        
        current_path = os.path.join(current_path, match)
        
    return current_path

def get_available_seasons(raw_data_dir="data/raw"):
    """Scans the raw data folder and returns a list of subfolders (seasons)."""
    if not os.path.exists(raw_data_dir):
        return []
    seasons = [
        d for d in os.listdir(raw_data_dir) 
        if os.path.isdir(os.path.join(raw_data_dir, d)) and not d.startswith(".")
    ]
    return sorted(seasons, reverse=True)

def load_all_game_options(boxscore_dir):
    """Scans the boxscore folder to return a list of available games with clean titles."""
    if not boxscore_dir or not os.path.exists(boxscore_dir):
        return []
    files = glob.glob(os.path.join(boxscore_dir, "*.xlsx"))
    options = []
    for f in files:
        base = os.path.basename(f)
        
        # Clean up the name
        name_part = base.lower().replace("boxscore_", "").replace(".xlsx", "")
        
        # If the filename contains "vs", cleanly separate teams
        if "vs" in name_part:
            parts = name_part.split("vs")
            team1 = parts[0].replace("_", " ").strip().title()
            team2 = parts[1].replace("_", " ").strip().title()
            team1 = " ".join(team1.split())
            team2 = " ".join(team2.split())
            display_name = f"{team1} vs {team2}"
        else:
            cleaned = name_part.replace("_", " ").title()
            display_name = " ".join(cleaned.split())
            
        options.append({"path": f, "name": display_name, "filename": base})
    return options

def parse_boxscore(file_path):
    """
    Parses the custom boxscore spreadsheet.
    Separates the team summaries from the individual player performance blocks.
    """
    team_df = pd.read_excel(file_path, header=0, nrows=2)
    full_sheet = pd.read_excel(file_path, header=None)
    
    jugador_rows = full_sheet[full_sheet.eq("JUGADOR").any(axis=1)].index.tolist()
    
    if len(jugador_rows) < 2:
        raise ValueError("Could not find the 'JUGADOR' header blocks in the boxscore sheet.")
        
    t1_name = str(full_sheet.iloc[jugador_rows[0] - 1, 0]).strip()
    t1_players = pd.read_excel(file_path, skiprows=jugador_rows[0])
    
    slice_idx = jugador_rows[1] - jugador_rows[0] - 2
    t1_players = t1_players.iloc[:slice_idx].dropna(subset=["JUGADOR"]).copy()
    
    t2_name = str(full_sheet.iloc[jugador_rows[1] - 1, 0]).strip()
    t2_players = pd.read_excel(file_path, skiprows=jugador_rows[1]).dropna(subset=["JUGADOR"]).copy()
    
    # Strip any potential leading/trailing whitespace inside column names
    t1_players.columns = t1_players.columns.str.strip()
    t2_players.columns = t2_players.columns.str.strip()
    
    # Clean and format player TIME columns uniformly
    t1_players["TIME"] = t1_players["TIME"].apply(format_time_cleanly)
    t2_players["TIME"] = t2_players["TIME"].apply(format_time_cleanly)
    
    return team_df, (t1_name, t1_players), (t2_name, t2_players)

def parse_pbp(file_path):
    """Reads the 3 distinct sheets of the PBP file."""
    xls = pd.ExcelFile(file_path)
    pbp_df = pd.read_excel(xls, sheet_name=0)
    shot_zone_df = pd.read_excel(xls, sheet_name=1)
    lineups_df = pd.read_excel(xls, sheet_name=2)
    return pbp_df, shot_zone_df, lineups_df

def parse_aggregate(file_path):
    """
    Loads Aggregate Offense, Defense, and compiles all team sheets
    into one master seasonal player list.
    """
    xls = pd.ExcelFile(file_path)
    offense_df = pd.read_excel(xls, sheet_name=0)
    defense_df = pd.read_excel(xls, sheet_name=1)
    
    all_players = []
    for sheet_name in xls.sheet_names[2:]:
        df_players = pd.read_excel(xls, sheet_name=sheet_name)
        df_players["Team"] = sheet_name
        df_players = df_players.dropna(subset=["JUGADOR"]).copy()
        
        # Clean and format player aggregate TIME columns
        df_players["TIME"] = df_players["TIME"].apply(format_time_cleanly)
        
        all_players.append(df_players)
        
    master_players = pd.concat(all_players, ignore_index=True)
    return offense_df, defense_df, master_players

# --- HELPERS FOR TIME ROUNDING & MULTI-METRIC PBP ALIGNMENT ---

def parse_time_to_minutes(val):
    """
    Highly resilient converter that parses strings (MM:SS), floats,
    datetime.time, and Excel datetimes to clean decimal minutes.
    """
    if pd.isna(val):
        return 0.0
        
    # 1. Handle Python datetime.time objects
    if isinstance(val, datetime.time):
        return val.hour * 60 + val.minute + val.second / 60.0
        
    # 2. Handle Python datetime.datetime objects (Excel parses MM:SS as HH:MM:00)
    if isinstance(val, datetime.datetime):
        return val.hour + val.minute / 60.0 + val.second / 3600.0
        
    val_str = str(val).strip()
    
    # Strip any date prefixes (e.g. "1899-12-31 22:09:00")
    if " " in val_str:
        val_str = val_str.split(" ")[-1]
        
    if ":" in val_str:
        parts = val_str.split(":")
        if len(parts) == 3:
            try:
                h = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                if h == 0:
                    return m + s / 60.0
                else:
                    if s == 0:
                        return h + m / 60.0
                    else:
                        return h * 60 + m + s / 60.0
            except ValueError:
                return 0.0
        elif len(parts) == 2:
            try:
                return float(parts[0]) + float(parts[1]) / 60.0
            except ValueError:
                return 0.0
    else:
        try:
            return float(val_str)
        except ValueError:
            return 0.0

def format_time_cleanly(val):
    """Converts numeric or string times into a clean, unified MM:SS format."""
    if pd.isna(val):
        return "00:00"
    try:
        if isinstance(val, str) and ":" in val:
            return val.strip()
        num_val = float(val)
        minutes = int(num_val)
        seconds = int(round((num_val - minutes) * 60))
        if seconds >= 60:
            minutes += 1
            seconds = 0
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return str(val).strip()

def get_total_team_minutes(players_df):
    """Sums individual player times to get total team playtime in minutes."""
    if "TIME" not in players_df.columns:
        return 200.0
    total_minutes = 0.0
    for val in players_df["TIME"]:
        total_minutes += parse_time_to_minutes(val)
    return total_minutes

def round_to_plausible_game_time(total_minutes):
    """
    Rounds parsed team minutes to standard regulation/OT durations.
    Added 160 minutes (32-minute cadet/junior) and 180 minutes profiles.
    """
    plausible_times = [150, 160, 180, 200, 225, 250, 275, 300]
    return min(plausible_times, key=lambda x: abs(x - total_minutes))

def estimate_game_duration(players_df1, players_df2, pbp_df=None):
    """
    Estimates the standard game duration (e.g., 32, 40, 45, 50 mins) based on:
    1. Maximum period (quarter) in PBP file (if available).
    2. Sum of player minutes from boxscores (as fallback).
    """
    if pbp_df is not None and not pbp_df.empty and "quarter" in pbp_df.columns:
        max_quarter = pbp_df["quarter"].max()
        if max_quarter <= 4:
            t1_mins = get_total_team_minutes(players_df1)
            t2_mins = get_total_team_minutes(players_df2)
            max_mins = max(t1_mins, t2_mins)
            if max_mins < 180 and max_mins > 0:
                return 32  # Cadet
            return 40  # Regulation 40m
        else:
            ot_periods = max_quarter - 4
            return 40 + ot_periods * 5
            
    t1_mins = get_total_team_minutes(players_df1)
    t2_mins = get_total_team_minutes(players_df2)
    max_mins = max(t1_mins, t2_mins)
    
    if max_mins > 235:
        return 50  # 2 OT
    elif max_mins > 210:
        return 45  # 1 OT
    elif max_mins > 180:
        return 40  # Regulation
    elif max_mins > 145:
        return 32  # Junior
    else:
        return 40  # Fallback

def normalize_and_format_player_times(players_df, target_minutes):
    """
    Scales and normalizes individual player times proportionally so their 
    sum perfectly equals standard target game minutes (e.g. 200 or 225).
    """
    if "TIME" not in players_df.columns or players_df.empty:
        return players_df
        
    raw_minutes = players_df["TIME"].apply(parse_time_to_minutes)
    total_raw = raw_minutes.sum()
    
    if total_raw == 0:
        return players_df
        
    scale_factor = target_minutes / total_raw
    scaled_minutes = raw_minutes * scale_factor
    
    # Format back to standardized clean MM:SS
    players_df["TIME"] = scaled_minutes.apply(format_time_cleanly)
    return players_df

def find_best_matching_pbp(t1_name, t2_name, pbp_dir, boxscore_filename):
    """
    Finds PBP files via multiple matching fallbacks:
    1. Team Name Overlaps (extracted from sheet)
    2. Date/ID matching based on filename numbers
    3. Flat file directories fallback (if only 1 file exists)
    """
    if not pbp_dir or not os.path.exists(pbp_dir):
        return None
        
    pbp_files = [f for f in os.listdir(pbp_dir) if f.lower().endswith((".xlsx", ".xls"))]
    if not pbp_files:
        return None
        
    t1_words = set(re.findall(r'\w+', t1_name.lower()))
    t2_words = set(re.findall(r'\w+', t2_name.lower()))
    for common in ["cb", "c", "b", "1", "2", "3", "a", "basket", "basquet", "club", "unio", "esportiva"]:
        t1_words.discard(common)
        t2_words.discard(common)
        
    best_file = None
    best_score = 0
    
    for pf in pbp_files:
        pf_lower = pf.lower()
        t1_matches = sum(1 for w in t1_words if w in pf_lower)
        t2_matches = sum(1 for w in t2_words if w in pf_lower)
        
        if t1_matches >= 1 and t2_matches >= 1:
            score = t1_matches + t2_matches
            if score > best_score:
                best_score = score
                best_file = pf
                
    if best_file:
        return os.path.join(pbp_dir, best_file)
        
    box_numbers = re.findall(r'\d+', boxscore_filename)
    if box_numbers:
        longest_num = max(box_numbers, key=len)
        if len(longest_num) >= 4:
            for pf in pbp_files:
                if longest_num in pf:
                    return os.path.join(pbp_dir, pf)
                    
    if len(pbp_files) == 1:
        return os.path.join(pbp_dir, pbp_files[0])
        
    return None

def tag_shot_team(pbp_df, t1_name, t2_name):
    """Tags each play with the correct team name based on team stats columns."""
    pbp_df = pbp_df.copy()
    pbp_df["Shot_Team"] = "Desconegut"
    
    team_a_mask = (pbp_df["FGA_A"] == 1) | (pbp_df["FGM_A"] == 1) | (pbp_df["2PA_A"] == 1) | (pbp_df["3PA_A"] == 1) | (pbp_df["FTA_A"] == 1)
    pbp_df.loc[team_a_mask, "Shot_Team"] = t1_name
    
    team_b_mask = (pbp_df["FGA_B"] == 1) | (pbp_df["FGM_B"] == 1) | (pbp_df["2PA_B"] == 1) | (pbp_df["3PA_B"] == 1) | (pbp_df["FTA_B"] == 1)
    pbp_df.loc[team_b_mask, "Shot_Team"] = t2_name
    
    return pbp_df

def get_dir_cache_key(directory):
    """Calculates a unique cache key based on the count and modification times of files."""
    if not directory or not os.path.exists(directory):
        return 0
    try:
        files = [os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith((".xlsx", ".xls"))]
        if not files:
            return 0
        return sum(os.path.getmtime(f) for f in files) + len(files)
    except OSError:
        return len(os.listdir(directory))

@st.cache_data
def load_and_aggregate_season_lineups(pbp_dir, selected_team, cache_key):
    """
    Scans PBP directory, aggregates lineups, and calculates advanced stats 
    (Rebounds, 2P/3P Volumes & Percentages) with dynamic caching.
    Returns both aggregated and raw combined dataframes.
    """
    if not pbp_dir or not os.path.exists(pbp_dir):
        return pd.DataFrame(), pd.DataFrame()
        
    pbp_files = [os.path.join(pbp_dir, f) for f in os.listdir(pbp_dir) if f.lower().endswith((".xlsx", ".xls"))]
    if not pbp_files:
        return pd.DataFrame(), pd.DataFrame()
        
    all_lineups = []
    for pf in pbp_files:
        try:
            xls = pd.ExcelFile(pf)
            if len(xls.sheet_names) < 3:
                continue
            df_lineups = pd.read_excel(xls, sheet_name=2)
            
            team_col = None
            for col in df_lineups.columns:
                if df_lineups[col].astype(str).str.contains(selected_team, na=False).any():
                    team_col = col
                    break
                    
            if team_col is not None:
                df_team = df_lineups[df_lineups[team_col] == selected_team].copy()
                all_lineups.append(df_team)
        except Exception:
            continue
            
    if not all_lineups:
        return pd.DataFrame(), pd.DataFrame()
        
    combined_df = pd.concat(all_lineups, ignore_index=True)
    combined_df.columns = combined_df.columns.str.strip()
    
    for col in combined_df.columns:
        col_lower = col.lower()
        if "oreb_for" in col_lower or "orb_for" in col_lower:
            combined_df["RO_For"] = combined_df[col]
        elif "dreb_for" in col_lower or "drb_for" in col_lower:
            combined_df["RD_For"] = combined_df[col]
        elif "oreb_agn" in col_lower or "orb_agn" in col_lower:
            combined_df["RO_Agn"] = combined_df[col]
        elif "dreb_agn" in col_lower or "drb_agn" in col_lower:
            combined_df["RD_Agn"] = combined_df[col]

    if "Lineup" not in combined_df.columns:
        if all(c in combined_df.columns for c in ["P1", "P2", "P3", "P4", "P5"]):
            combined_df["Lineup"] = combined_df[["P1", "P2", "P3", "P4", "P5"]].apply(
                lambda row: ", ".join(sorted([str(row["P1"]), str(row["P2"]), str(row["P3"]), str(row["P4"]), str(row["P5"])])), axis=1
            )
        else:
            return pd.DataFrame(), pd.DataFrame()
            
    numeric_cols = [
        "PTS_For", "PTS_Agn", "+/-", "FTM_For", "FTA_For", "FTM_Agn", "FTA_Agn", 
        "FOULS_Cor", "FOULS_Dra", "TOV_For", "TOV_Agn",
        "RO_For", "RD_For", "RO_Agn", "RD_Agn"
    ]
    
    for col in combined_df.columns:
        col_lower = col.lower()
        if any(z in col_lower for z in ["rim", "paint", "mr", "cor", "atb"]):
            if any(term in col_lower for term in ["fga", "fgm", "%", "pct"]):
                numeric_cols.append(col)
                
    available_numeric = [c for c in list(set(numeric_cols)) if c in combined_df.columns]
    
    for c in available_numeric:
        combined_df[c] = pd.to_numeric(combined_df[c], errors="coerce").fillna(0.0)
        
    agg_dict = {c: "sum" for c in available_numeric}
    for c in ["P1", "P2", "P3", "P4", "P5"]:
        if c in combined_df.columns:
            agg_dict[c] = "first"
            
    aggregated = combined_df.groupby("Lineup").agg(agg_dict).reset_index()
    
    for suffix in ["_For", "_Agn"]:
        fga_2p = f"2PA{suffix}"
        fgm_2p = f"2PM{suffix}"
        pct_2p = f"2P%{suffix}"
        if fga_2p in aggregated.columns and fgm_2p in aggregated.columns:
            aggregated[pct_2p] = (aggregated[fgm_2p] / aggregated[fga_2p] * 100.0).fillna(0.0)
            
        fga_3p = f"3PA{suffix}"
        fgm_3p = f"3PM{suffix}"
        pct_3p = f"3P%{suffix}"
        if fga_3p in aggregated.columns and fgm_3p in aggregated.columns:
            aggregated[pct_3p] = (aggregated[fgm_3p] / aggregated[fga_3p] * 100.0).fillna(0.0)
            
    if "+/-" in aggregated.columns:
        aggregated = aggregated.sort_values("+/-", ascending=False)
        
    return aggregated, combined_df

@st.cache_data
def load_all_raw_game_boxscores(boxscore_dir, pbp_dir, cache_key):
    """
    Scans the boxscores directory, reads team-level summaries for all games,
    and dynamically aligns them with their correct Week (Jornada) by looking up the PBP lineups.
    """
    if not boxscore_dir or not os.path.exists(boxscore_dir):
        return pd.DataFrame()
        
    files = glob.glob(os.path.join(boxscore_dir, "*.xlsx"))
    all_game_summaries = []
    
    for f in files:
        try:
            # 1. Read team aggregate totals (first 2 rows)
            team_df = pd.read_excel(f, header=0, nrows=2)
            team_df.columns = team_df.columns.str.strip()
            
            # Clean and format game names
            base = os.path.basename(f)
            game_name = base.replace("boxscore_", "").replace(".xlsx", "").replace("_", " ").title()
            game_name = " ".join(game_name.split())
            
            team_df["Game_File"] = base
            team_df["Game_Name"] = game_name
            
            # 2. Extract Week (Jornada) from the matching PBP lineups sheet
            t1_name = str(team_df.iloc[0].get("Team", "")).strip()
            t2_name = str(team_df.iloc[1].get("Team", "")).strip()
            pbp_path = find_best_matching_pbp(t1_name, t2_name, pbp_dir, base)
            
            # canvi: Cerca de capçalera intel·ligent per extreure el valor numèric real en lloc de la paraula "Week"
            week_val = None
            if pbp_path and os.path.exists(pbp_path):
                try:
                    xls = pd.ExcelFile(pbp_path)
                    if len(xls.sheet_names) >= 3:
                        df_lin = pd.read_excel(xls, sheet_name=2, nrows=5)
                        # Netegem els noms de les columnes per cercar "week" de manera robusta
                        df_lin.columns = df_lin.columns.str.strip().str.lower()
                        week_cols = [c for c in df_lin.columns if "week" in str(c)]
                        
                        if week_cols and not df_lin.empty:
                            week_val = df_lin[week_cols[0]].iloc[0]
                        else:
                            # Fallback a la segona columna de fons en cas d'un disseny sense nom de capçalera
                            week_val = df_lin.iloc[0, 1]
                except Exception:
                    pass

                    
            # Fallback si no troba el PBP de fons
            if week_val is None or pd.isna(week_val):
                nums = re.findall(r'\b\d{1,2}\b', base)
                if nums:
                    week_val = f"Jornada {nums[0]}"
                else:
                    week_val = "Altres"
            else:
                week_val = f"Jornada {int(float(week_val))}" if isinstance(week_val, (int, float)) else f"Jornada {week_val}"
                
            team_df["Week"] = week_val
            all_game_summaries.append(team_df)
        except Exception:
            continue
            
    if not all_game_summaries:
        return pd.DataFrame()
        
    return pd.concat(all_game_summaries, ignore_index=True)
def get_team_logo_path(team_name, selected_season, raw_dir="data/raw"):
    """
    Attempts to find a matching team logo image (.png, .jpg, .jpeg) case-insensitively.
    Ignores spaces, underscores, and hyphens to guarantee matches.
    """
    logos_dir = resolve_path_case_insensitive(raw_dir, selected_season, "logos")
    if not logos_dir or not os.path.exists(logos_dir):
        return None
        
    # canvi: Neteja estricta de caràcters especials en el nom cercat (ex: "BARICENTRO BARBERA" -> "baricentrobarbera")
    clean_target = re.sub(r'[\s_\-]', '', str(team_name)).lower().strip()
    
    try:
        entries = os.listdir(logos_dir)
    except OSError:
        return None
        
    for entry in entries:
        entry_lower = entry.lower()
        # Neteja de caràcters especials en el nom de l'arxiu real de GitHub
        clean_entry = re.sub(r'[\s_\-]', '', entry_lower).replace(".png", "").replace(".jpg", "").replace(".jpeg", "")
        
        if clean_target in clean_entry and entry_lower.endswith((".png", ".jpg", ".jpeg")):
            return os.path.join(logos_dir, entry)
            
    return None
def get_team_logo_base64_url(team_name, selected_season):
    """
    Finds the team logo, reads it, encodes it, and returns a fully qualified
    base64 Data URL safe for st.column_config.ImageColumn in table cells.
    """
    path = get_team_logo_path(team_name, selected_season)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(path)[1].lower().replace(".", "")
        if ext not in ["png", "jpg", "jpeg"]:
            ext = "png"
        return f"data:image/{ext};base64,{encoded}"
    except Exception:
        return None
    # Afegeix-ho a baix de tot de /utils/data_loader.py:
def calculate_combo_stats_metrics(df):
    """
    Calculates advanced statistics (eFG%, TO%, RO, RD) on an aggregated lineup subset
    using the exact zone-level columns from the excel sheet.
    """
    if df.empty:
        return 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0
        
    # Classificació dinàmica d'un sol pas
    ro = 0
    rd = 0
    ro_ag = 0
    rd_ag = 0
    
    tov_for = 0.0
    fta_for = 0.0
    tov_agn = 0.0
    fta_agn = 0.0
    
    for col in df.columns:
        col_lower = col.lower()
        col_sum = df[col].sum()
        
        # Pèrdues
        if "tov" in col_lower:
            if "for" in col_lower:
                tov_for += col_sum
            elif "agn" in col_lower or "ag" in col_lower:
                tov_agn += col_sum
                
        # Tirs lliures
        elif "fta" in col_lower:
            if "for" in col_lower:
                fta_for += col_sum
            elif "agn" in col_lower or "ag" in col_lower:
                fta_agn += col_sum
                
        # Rebot Ofensiu (RO)
        elif any(p in col_lower for p in ["oreb", "orb", "ro_"]):
            is_off_reb = any(p in col_lower for p in ["oreb", "orb"]) or col_lower.startswith("ro") or "ro_for" in col_lower or "ro_agn" in col_lower or "ro_ag" in col_lower
            if is_off_reb:
                if "for" in col_lower:
                    ro += int(col_sum)
                elif "agn" in col_lower or "ag" in col_lower:
                    ro_ag += int(col_sum)
                    
        # Rebot Defensiu (RD)
        elif any(p in col_lower for p in ["dreb", "drb", "rd_"]):
            is_def_reb = any(p in col_lower for p in ["dreb", "drb"]) or col_lower.startswith("rd") or "rd_for" in col_lower or "rd_agn" in col_lower or "rd_ag" in col_lower
            if is_def_reb:
                if "for" in col_lower:
                    rd += int(col_sum)
                elif "agn" in col_lower or "ag" in col_lower:
                    rd_ag += int(col_sum)

    # Recompte de zones de tir
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
    
    poss_for = fga_for + 0.44 * fta_for + tov_for
    to_pct = (tov_for / poss_for * 100.0) if poss_for > 0 else 0.0
    
    poss_agn = fga_agn + 0.44 * fta_agn + tov_agn
    to_pct_ag = (tov_agn / poss_agn * 100.0) if poss_agn > 0 else 0.0
    
    return off_efg, def_efg, to_pct, to_pct_ag, ro, ro_ag, rd, rd_ag