import pandas as pd
import numpy as np
import glob
import os
import re

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

# --- REFINED HELPERS FOR ACCESS CONTROL & TIME ROUNDING ---

def parse_time_to_minutes(time_str):
    """Parses standard MM:SS string or float representations into float minutes."""
    try:
        if pd.isna(time_str):
            return 0.0
        time_str = str(time_str).strip()
        if ":" in time_str:
            parts = time_str.split(":")
            return float(parts[0]) + float(parts[1]) / 60.0
        else:
            return float(time_str)
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
    """Rounds parsed team minutes to standard regulation/OT durations (e.g. 200, 225, 250)."""
    plausible_times = [200, 225, 250, 275, 300]
    return min(plausible_times, key=lambda x: abs(x - total_minutes))

def find_best_matching_pbp(boxscore_filename, pbp_dir):
    """
    Matches boxscore files to PBP files inside the directory based on overlapping terms,
    allowing for minor prefix/suffix differences and different score tracking names.
    """
    if not pbp_dir or not os.path.exists(pbp_dir):
        return None
        
    box_clean = boxscore_filename.lower().replace("boxscore_", "").replace(".xlsx", "")
    box_words = set(re.findall(r'\w+', box_clean))
    box_words.discard("analysis")
    box_words.discard("vs")
    
    pbp_files = [f for f in os.listdir(pbp_dir) if f.lower().endswith(".xlsx")]
    if not pbp_files:
        return None
        
    best_match = None
    max_overlap = 0
    
    for pf in pbp_files:
        pbp_clean = pf.lower().replace("pbp_", "").replace(".xlsx", "")
        pbp_words = set(re.findall(r'\w+', pbp_clean))
        pbp_words.discard("analysis")
        pbp_words.discard("vs")
        
        overlap = len(box_words.intersection(pbp_words))
        if overlap > max_overlap:
            max_overlap = overlap
            best_match = pf
            
    if max_overlap >= 1:
        return os.path.join(pbp_dir, best_match)
    return None