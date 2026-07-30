import pandas as pd
import numpy as np
import glob
import os
def get_available_seasons(raw_data_dir="data/raw"):
    """
    Scans the raw data folder and returns a list of available season folders.
    Sorts them in reverse chronological order (newest first).
    """
    if not os.path.exists(raw_data_dir):
        return []
    # Identify directories inside raw/
    seasons = [
        d for d in os.listdir(raw_data_dir) 
        if os.path.isdir(os.path.join(raw_data_dir, d))
    ]
    return sorted(seasons, reverse=True)
def load_all_game_options(boxscore_dir):
    """Scans the boxscore folder to return a list of available games."""
    files = glob.glob(os.path.join(boxscore_dir, "*.xlsx"))
    options = []
    for f in files:
        base = os.path.basename(f)
        # Assuming filename is formatted like: boxscore_TEAM1_TEAM2.xlsx or similar
        display_name = base.replace("boxscore_", "").replace(".xlsx", "").replace("_", " vs ")
        options.append({"path": f, "name": display_name, "filename": base})
    return options

def parse_boxscore(file_path):
    """
    Parses the custom boxscore spreadsheet.
    Separates the team summaries from the individual player performance blocks.
    """
    # 1. Read team-level metrics (First 3 rows)
    team_df = pd.read_excel(file_path, header=0, nrows=2)
    
    # 2. Read full spreadsheet to find where JUGADOR headers start
    full_sheet = pd.read_excel(file_path, header=None)
    
    # Find row indices where "JUGADOR" is written
    jugador_rows = full_sheet[full_sheet.eq("JUGADOR").any(axis=1)].index.tolist()
    
    if len(jugador_rows) < 2:
        raise ValueError("Could not find the 'JUGADOR' header blocks in the boxscore sheet.")
        
    # Team 1 details
    t1_name = str(full_sheet.iloc[jugador_rows[0] - 1, 0]).strip()
    t1_players = pd.read_excel(file_path, skiprows=jugador_rows[0] + 1)
    # Stop before Team 2 starts
    t1_players = t1_players.iloc[: jugador_rows[1] - jugador_rows[0] - 3].dropna(subset=["JUGADOR"])
    
    # Team 2 details
    t2_name = str(full_sheet.iloc[jugador_rows[1] - 1, 0]).strip()
    t2_players = pd.read_excel(file_path, skiprows=jugador_rows[1] + 1).dropna(subset=["JUGADOR"])
    
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
    
    # Iterate over all remaining tabs (one tab per team) to pool all player data
    all_players = []
    for sheet_name in xls.sheet_names[2:]:
        df_players = pd.read_excel(xls, sheet_name=sheet_name)
        df_players["Team"] = sheet_name  # Track which team player belongs to
        # Standardize empty space/cleaning if needed
        df_players = df_players.dropna(subset=["JUGADOR"])
        all_players.append(df_players)
        
    master_players = pd.concat(all_players, ignore_index=True)
    return offense_df, defense_df, master_players