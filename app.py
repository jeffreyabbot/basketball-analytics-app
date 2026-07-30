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
    round_to_plausible_game_time,
    find_best_matching_pbp,
    parse_time_to_minutes
)
from utils.court_visualizer import draw_colorblind_shot_chart

# Page config & Theme (Must be first)
st.set_page_config(page_title="Analítica Copa Catalunya", layout="wide")

# Simple Access Control Gating
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.title("🔒 Staff Login Analítica Copa Catalunya")
        correct_password = st.secrets.get("auth", {}).get("password", None)
        
        if not correct_password:
            st.error("Access control secrets are missing. Contact administrator.")
            st.stop()
            
        entered_password = st.text_input("Enter Staff Password", type="password")
        if st.button("Login"):
            if entered_password == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()

check_password()

RAW_DIR = "data/raw"

CB_BLUE = "#1f77b4"
CB_ORANGE = "#ff7f0e"
CB_NEUTRAL = "#4a4a4a"

st.sidebar.title("🏀 Coaching Hub")

# 1. Season Selector in Sidebar
seasons = get_available_seasons(RAW_DIR)

if not seasons:
    st.sidebar.error("Please create a season folder (e.g., 'Copa_2025_2026') inside data/raw/")
    st.info("Structure your folders as: `data/raw/YOUR_SEASON_NAME/pbp/`, etc.")
    st.stop()

selected_season = st.sidebar.selectbox("Select Season", seasons)

# 2. Dynamically resolve paths case-insensitively with Fallbacks
PBP_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "pbp")
if not PBP_DIR or not os.path.exists(PBP_DIR):
    PBP_DIR = resolve_path_case_insensitive(RAW_DIR, "pbp")

BOX_DIR = resolve_path_case_insensitive(RAW_DIR, selected_season, "boxscores")
if not BOX_DIR or not os.path.exists(BOX_DIR):
    BOX_DIR = resolve_path_case_insensitive(RAW_DIR, "boxscores")

AGG_FILE = resolve_path_case_insensitive(RAW_DIR, selected_season, "aggregate", "aggregate_season_latest.xlsx")
if not AGG_FILE or not os.path.exists(AGG_FILE):
    AGG_FILE = resolve_path_case_insensitive(RAW_DIR, "aggregate", "aggregate_season_latest.xlsx")

# 3. View selector
view = st.sidebar.radio("Navigate Views", ["Game Analyzer", "League & Season Trends", "Player Shooting Index"])

# ----------------- VIEW 1: GAME ANALYZER -----------------
if view == "Game Analyzer":
    st.title(f"Game Analyzer ({selected_season.replace('_', ' ')})")
    
    if not BOX_DIR or not os.path.exists(BOX_DIR):
        st.info("No boxscore directory found in raw data folder. Please check path names (case-insensitive).")
    else:
        games = load_all_game_options(BOX_DIR)
        
        if not games:
            st.info("No games loaded in raw folders. Please add your weekly boxscore/pbp Excel files to the directories.")
        else:
            selected_game = st.selectbox("Select Matchup", games, format_func=lambda g: g["name"])
            
            # Parse data
            team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])
            
            # Calculate standard plausible game duration based on player times
            t1_mins = get_total_team_minutes(t1_players)
            t2_mins = get_total_team_minutes(t2_players)
            game_total_mins = max(t1_mins, t2_mins)
            rounded_game_mins = round_to_plausible_game_time(game_total_mins)
            
            # Fuzzy match PBP files dynamically
            pbp_path = find_best_matching_pbp(selected_game["filename"], PBP_DIR)
            has_pbp = pbp_path is not None and os.path.exists(pbp_path)
            if has_pbp:
                pbp_df, shot_zone_df, lineups_df = parse_pbp(pbp_path)
            
            # --- Subsection 1: Advanced Metrics (OER/DER/PACE) ---
            st.subheader("Team Efficiency Ratings")
            col1, col2, col3, col4 = st.columns(4)
            
            t1_stats = team_summary.iloc[0]
            t2_stats = team_summary.iloc[1]
            
            with col1:
                st.metric(label="Possessions (Pace)", value=f"{t1_stats['POSScal']:.1f}")
            with col2:
                st.metric(label=f"{t1_name} OER / DER", value=f"{t1_stats['OERcal']:.1f} / {t1_stats['DERcal']:.1f}")
            with col3:
                st.metric(label=f"{t2_name} OER / DER", value=f"{t2_stats['OERcal']:.1f} / {t2_stats['DERcal']:.1f}")
            with col4:
                st.metric(
                    label="Rounded Game Time", 
                    value=f"{rounded_game_mins // 5} mins", 
                    help=f"Raw summed player minutes: {game_total_mins:.1f} rounded to closest standard {rounded_game_mins} total player minutes."
                )
                
            # --- Subsection 2: Four Factors Comparison ---
            st.subheader("Four Factors Comparison")
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
            st.subheader("Player Performance Profiles")
            
            # View Selector for Boxscores to prevent page horizontal scroll
            stat_view = st.radio(
                "Select Boxscore View", 
                ["Standard Boxscore", "Advanced Metrics", "Shooting Zone Splits"], 
                horizontal=True
            )
            
            # Standard columns groupings
            standard_cols = ["JUGADOR", "TIME", "PTS", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA", "ORB", "DRB", "AS", "STL", "BLK", "TO", "F", "F+"]
            advanced_cols = ["JUGADOR", "TIME", "EFI", "USG%cal", "eFG%", "TS%", "FTR", "TO%cal", "PTS/PLAYcal", "TOpts", "2CPts"]
            zone_cols = ["JUGADOR", "Rim FGM", "Rim FGA", "Rim %", "Paint FGM", "Paint FGA", "Paint %", "MR FGM", "MR FGA", "MR %", "Cor3 FGM", "Cor3 FGA", "Cor3 %", "ATB3 FGM", "ATB3 FGA", "ATB3 %"]

            team_tab1, team_tab2 = st.tabs([t1_name, t2_name])
            
            for tab, players_df in zip([team_tab1, team_tab2], [t1_players, t2_players]):
                with tab:
                    # Filter columns dynamically based on selection and file headers
                    if stat_view == "Standard Boxscore":
                        selected_cols = [c for c in standard_cols if c in players_df.columns]
                    elif stat_view == "Advanced Metrics":
                        selected_cols = [c for c in advanced_cols if c in players_df.columns]
                    else:
                        selected_cols = [c for c in zone_cols if c in players_df.columns]
                        
                    st.dataframe(players_df[selected_cols].style.format(precision=2), use_container_width=True)
                
            # --- Subsection 4: PBP-Specific Tabs ---
            if has_pbp:
                st.markdown("---")
                st.subheader("Game Flow and Lineups")
                pbp_tab, lineup_tab = st.tabs(["Shot Charts & Play Log", "Active Lineups Index"])
                
                with pbp_tab:
                    all_players_list = ["All"] + sorted(list(pbp_df["Player"].dropna().unique()))
                    shot_player = st.selectbox("Filter Shot Locations by Player", all_players_list)
                    
                    chart_col, log_col = st.columns([2, 1])
                    with chart_col:
                        fig_shot = draw_colorblind_shot_chart(pbp_df, selected_player=shot_player)
                        st.plotly_chart(fig_shot, use_container_width=True)
                    with log_col:
                        st.write("Quarter/Time Event Feed")
                        st.dataframe(pbp_df[["quarter", "time", "text"]].dropna().head(100), height=500, use_container_width=True)
                        
                with lineup_tab:
                    st.write("On-Court Lineup Performance Records")
                    st.dataframe(lineups_df, use_container_width=True)
            else:
                st.warning("No matching Play-By-Play dataset found for this game. Fuzzy file matching could not find a PBP match in the directory.")

# ----------------- VIEW 2: LEAGUE & SEASON TRENDS -----------------
elif view == "League & Season Trends":
    st.title(f"League & Season Trends ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No aggregate file found. Place your `aggregate_season_latest.xlsx` file in the correct directory.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        tab_off, tab_def, tab_chart = st.tabs(["League Offense Leaderboard", "League Defense Leaderboard", "League Scatterplot"])
        
        with tab_off:
            st.write("Sorted League Efficiency (Offensive Metrics)")
            # Set explicit viewport height to show all teams on page
            st.dataframe(offense_df.sort_values("OERcal", ascending=False).style.format(precision=2), use_container_width=True, height=600)
            
        with tab_def:
            st.write("Sorted League Efficiency (Defensive Metrics)")
            st.dataframe(defense_df.sort_values("DERcal", ascending=True).style.format(precision=2), use_container_width=True, height=600)
            
        with tab_chart:
            st.write("Dynamic League Analysis Scatterplot")
            
            # Merge offense and defense to get complete metrics
            league_df = offense_df.merge(defense_df, on="Team", suffixes=("_Off", "_Def"))
            
            # Let the coaches select which metric to plot on X and Y
            col_scat1, col_scat2 = st.columns(2)
            with col_scat1:
                x_metric = st.selectbox(
                    "X Axis (Offensive Metric)", 
                    ["OERcal_Off", "eFG%_Off", "TOV%cal_Off", "ORB%cal_Off", "FTR_Off"],
                    format_func=lambda x: {
                        "OERcal_Off": "Offensive Rating (OER)",
                        "eFG%_Off": "Offensive eFG%",
                        "TOV%cal_Off": "Offensive Turnover Rate (TOV%)",
                        "ORB%cal_Off": "Offensive Rebounding % (ORB%)",
                        "FTR_Off": "Free Throw Rate (FTR)"
                    }[x]
                )
            with col_scat2:
                y_metric = st.selectbox(
                    "Y Axis (Defensive Metric)", 
                    ["DERcal_Off", "eFG%_Def", "TOV%cal_Def", "ORB%cal_Def", "FTR_Def"],
                    format_func=lambda y: {
                        "DERcal_Off": "Defensive Rating (DER)",
                        "eFG%_Def": "Defensive eFG% (Opp eFG%)",
                        "TOV%cal_Def": "Defensive Turnover Rate (Opp TOV%)",
                        "ORB%cal_Def": "Opponent Offensive Rebounding % (Opp ORB%)",
                        "FTR_Def": "Defensive Free Throw Rate (Opp FTR)"
                    }[y]
                )
            
            fig_scat = px.scatter(
                league_df,
                x=x_metric,
                y=y_metric,
                hover_name="Team",
                title="League Team Comparison Map",
                labels={
                    "OERcal_Off": "Offensive Rating (OER)",
                    "DERcal_Off": "Defensive Rating (DER)",
                    "eFG%_Off": "Offensive eFG%",
                    "eFG%_Def": "Defensive eFG% (Opp eFG%)",
                    "TOV%cal_Off": "Offensive TOV%",
                    "TOV%cal_Def": "Defensive TOV%",
                    "ORB%cal_Off": "Offensive Rebounding %",
                    "ORB%cal_Def": "Opponent Offensive Rebounding %",
                    "FTR_Off": "FTR",
                    "FTR_Def": "Def FTR"
                },
                color_discrete_sequence=[CB_BLUE]
            )
            
            # Add dynamic average lines
            mean_x = league_df[x_metric].mean()
            mean_y = league_df[y_metric].mean()
            fig_scat.add_vline(x=mean_x, line_dash="dash", line_color=CB_ORANGE, annotation_text="Avg Off")
            fig_scat.add_hline(y=mean_y, line_dash="dash", line_color=CB_ORANGE, annotation_text="Avg Def")
            
            # Reverse Y axis only if it is DER or Def eFG% (where lower is better)
            if y_metric in ["DERcal_Off", "eFG%_Def", "FTR_Def"]:
                fig_scat.update_yaxes(autorange="reversed")
                
            st.plotly_chart(fig_scat, use_container_width=True)

# ----------------- VIEW 3: PLAYER SHOOTING INDEX -----------------
elif view == "Player Shooting Index":
    st.title(f"Player Shooting Index ({selected_season.replace('_', ' ')})")
    
    if not AGG_FILE or not os.path.exists(AGG_FILE):
        st.info("No aggregate files loaded. Please ensure seasonal player excel data is placed in the correct directories.")
    else:
        _, _, master_players = parse_aggregate(AGG_FILE)
        
        # Clean numeric profiles
        master_players["GamesPlayed"] = pd.to_numeric(master_players["GamesPlayed"], errors='coerce')
        master_players["PTS"] = pd.to_numeric(master_players["PTS"], errors='coerce')
        master_players["eFG%"] = pd.to_numeric(master_players["eFG%"], errors='coerce')
        master_players["FGA"] = pd.to_numeric(master_players["FGA"], errors='coerce')
        
        # Parse TIME column to float minutes for numerical sorting/filtering
        master_players["MinPerGame"] = master_players["TIME"].apply(parse_time_to_minutes)
        
        st.write("Season aggregate player sorting engine. Filter by minimum performance thresholds.")
        
        # Leaderboard Filters
        st.subheader("Leaderboard Filters")
        col_filt1, col_filt2, col_filt3 = st.columns(3)
        with col_filt1:
            min_games = st.slider("Minimum Games Played", 1, int(master_players["GamesPlayed"].max() or 20), 5)
        with col_filt2:
            min_fga = st.slider("Minimum FGA per Game", 0.0, float(master_players["FGA"].max() or 20.0), 2.0, step=0.5)
        with col_filt3:
            min_mins = st.slider("Minimum Minutes per Game", 0.0, float(master_players["MinPerGame"].max() or 40.0), 10.0, step=1.0)
            
        filtered_players = master_players[
            (master_players["GamesPlayed"] >= min_games) &
            (master_players["FGA"] >= min_fga) &
            (master_players["MinPerGame"] >= min_mins)
        ]
        
        sort_metric = st.selectbox("Primary Sort Criteria", ["eFG%", "PTS", "GamesPlayed", "FGA", "MinPerGame"])
        sorted_players = filtered_players.sort_values(sort_metric, ascending=False)
        
        # Display clean structured dataframe
        view_cols = ["JUGADOR", "Team", "GamesPlayed", "TIME", "FGA", "PTS", "eFG%", "TS%", "Rim %", "Paint %", "MR %", "Cor3 %", "ATB3 %"]
        
        st.dataframe(
            sorted_players[view_cols].style.format({
                "TIME": "{}", # Time is formatted already as clear MM:SS string
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