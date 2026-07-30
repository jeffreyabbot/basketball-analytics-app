import pandas as pd
import numpy as np
import glob
import os

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
        if os.path.isdir(os.path.join(raw_data_dir, d))
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
            # Clean up duplicate spaces
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
    t1_players = t1_players.iloc[:slice_idx].dropna(subset=["JUGADOR"])
    
    t2_name = str(full_sheet.iloc[jugador_rows[1] - 1, 0]).strip()
    t2_players = pd.read_excel(file_path, skiprows=jugador_rows[1]).dropna(subset=["JUGADOR"])
    
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
        df_players = df_players.dropna(subset=["JUGADOR"])
        all_players.append(df_players)
        
    master_players = pd.concat(all_players, ignore_index=True)
    return offense_df, defense_df, master_players