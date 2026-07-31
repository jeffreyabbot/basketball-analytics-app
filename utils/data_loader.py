import pandas as pd
import numpy as np
import glob
import os
import re
import datetime

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
        
import pandas as pd
import numpy as np
import glob
import os
import re
import datetime

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

# --- REFINED HELPERS FOR TIME ROUNDING & MULTI-METRIC PBP ALIGNMENT ---

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
    # 1. Best: Use PBP quarters if available (accurate and robust)
    if pbp_df is not None and not pbp_df.empty and "quarter" in pbp_df.columns:
        max_quarter = pbp_df["quarter"].max()
        if max_quarter <= 4:
            # Check if total player minutes are low, indicating youth 32m league
            t1_mins = get_total_team_minutes(players_df1)
            t2_mins = get_total_team_minutes(players_df2)
            max_mins = max(t1_mins, t2_mins)
            if max_mins < 180 and max_mins > 0:
                return 32  # Partits de cadet/infantil (32 minuts totals)
            return 40  # Partit de 40 minuts reglamentaris
        else:
            # Cada pròrroga (OT) suma 5 minuts
            ot_periods = max_quarter - 4
            return 40 + ot_periods * 5
            
    # 2. Fallback: Use summed team minutes
    t1_mins = get_total_team_minutes(players_df1)
    t2_mins = get_total_team_minutes(players_df2)
    max_mins = max(t1_mins, t2_mins)
    
    if max_mins > 235:
        return 50  # 2 OT FIBA (50 minuts)
    elif max_mins > 210:
        return 45  # 1 OT FIBA (45 minuts)
    elif max_mins > 180:
        return 40  # Reglamentari FIBA (40 minuts)
    elif max_mins > 145:
        return 32  # Cadet/Infantil (32 minuts)
    else:
        return 40  # Fallback per defecte

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
        
    # Attempt 1: Match by Team Name keywords (Strongest)
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
        
    # Attempt 2: Match by date/numbers inside the filename (Fallback)
    box_numbers = re.findall(r'\d+', boxscore_filename)
    if box_numbers:
        longest_num = max(box_numbers, key=len)
        if len(longest_num) >= 4:  # Match only on dates/game IDs
            for pf in pbp_files:
                if longest_num in pf:
                    return os.path.join(pbp_dir, pf)
                    
    # Attempt 3: If only one PBP file exists, default to it
    if len(pbp_files) == 1:
        return os.path.join(pbp_dir, pbp_files[0])
        
    return None
def tag_shot_team(pbp_df, t1_name, t2_name):
    """Tags each play with the correct team name based on team stats columns."""
    pbp_df = pbp_df.copy()
    pbp_df["Shot_Team"] = "Desconegut"
    
    # If any Team A stat is 1, it belongs to Team A
    team_a_mask = (pbp_df["FGA_A"] == 1) | (pbp_df["FGM_A"] == 1) | (pbp_df["2PA_A"] == 1) | (pbp_df["3PA_A"] == 1) | (pbp_df["FTA_A"] == 1)
    pbp_df.loc[team_a_mask, "Shot_Team"] = t1_name
    
    # If any Team B stat is 1, it belongs to Team B
    team_b_mask = (pbp_df["FGA_B"] == 1) | (pbp_df["FGM_B"] == 1) | (pbp_df["2PA_B"] == 1) | (pbp_df["3PA_B"] == 1) | (pbp_df["FTA_B"] == 1)
    pbp_df.loc[team_b_mask, "Shot_Team"] = t2_name
    
    return pbp_df
def load_and_aggregate_season_lineups(pbp_dir, selected_team):
    """
    Scans the PBP directory, opens all PBP files, extracts the lineups tab,
    and aggregates lineup statistics for the selected team across the entire season.
    """
    if not pbp_dir or not os.path.exists(pbp_dir):
        return pd.DataFrame()
        
    pbp_files = [os.path.join(pbp_dir, f) for f in os.listdir(pbp_dir) if f.lower().endswith((".xlsx", ".xls"))]
    if not pbp_files:
        return pd.DataFrame()
        
    all_lineups = []
    for pf in pbp_files:
        try:
            xls = pd.ExcelFile(pf)
            if len(xls.sheet_names) < 3:
                continue
            df_lineups = pd.read_excel(xls, sheet_name=2)
            
            # Find team column dynamically
            team_col = None
            for col in df_lineups.columns:
                if df_lineups[col].astype(str).str.contains(selected_team, na=False).any():
                    team_col = col
                    break
                    
            if team_col is not None:
                # Filter only rows for the selected team
                df_team = df_lineups[df_lineups[team_col] == selected_team].copy()
                all_lineups.append(df_team)
        except Exception:
            continue
            
    if not all_lineups:
        return pd.DataFrame()
        
    combined_df = pd.concat(all_lineups, ignore_index=True)
    combined_df.columns = combined_df.columns.str.strip()
    
    # Standardize player names order in Lineup string to ensure duplicates match
    if "Lineup" not in combined_df.columns:
        if all(c in combined_df.columns for c in ["P1", "P2", "P3", "P4", "P5"]):
            combined_df["Lineup"] = combined_df[["P1", "P2", "P3", "P4", "P5"]].apply(
                lambda row: ", ".join(sorted([str(row["P1"]), str(row["P2"]), str(row["P3"]), str(row["P4"]), str(row["P5"])])), axis=1
            )
        else:
            return pd.DataFrame()
            
    # Numeric columns to aggregate
    numeric_cols = ["PTS_For", "PTS_Agn", "+/-", "FTM_For", "FTA_For", "FTM_Agn", "FTA_Agn", "FOULS_Cor", "FOULS_Dra", "TOV_For", "TOV_Agn"]
    available_numeric = [c for c in numeric_cols if c in combined_df.columns]
    
    for c in available_numeric:
        combined_df[c] = pd.to_numeric(combined_df[c], errors="coerce").fillna(0.0)
        
    agg_dict = {c: "sum" for c in available_numeric}
    for c in ["P1", "P2", "P3", "P4", "P5"]:
        if c in combined_df.columns:
            agg_dict[c] = "first"
            
    # Group by standardized Lineup string
    aggregated = combined_df.groupby("Lineup").agg(agg_dict).reset_index()
    
    if "+/-" in aggregated.columns:
        aggregated = aggregated.sort_values("+/-", ascending=False)
        
    return aggregated