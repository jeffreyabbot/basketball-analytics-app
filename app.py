import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# Consolidated data loader imports
from utils.data_loader import (
    get_available_seasons, 
    load_all_game_options, 
    parse_boxscore, 
    parse_pbp, 
    parse_aggregate
)
from utils.court_visualizer import draw_colorblind_shot_chart

# Page config & Theme
st.set_page_config(page_title="Team Basketball Analytics", layout="wide")

RAW_DIR = "data/raw"

# High contrast/accessible color constants (Safe for deuteranopia & protanopia)
CB_BLUE = "#1f77b4"
CB_ORANGE = "#ff7f0e"
CB_NEUTRAL = "#4a4a4a"

st.sidebar.title("🏀 Coaching Hub")

# 1. Season Selector in Sidebar (Resolves first)
seasons = get_available_seasons(RAW_DIR)

if not seasons:
    st.sidebar.error("Please create a season folder (e.g., 'Copa_2025_2026') inside data/raw/")
    st.info("Structure your folders as: `data/raw/YOUR_SEASON_NAME/pbp/`, etc.")
    st.stop()

selected_season = st.sidebar.selectbox("Select Season", seasons)

# 2. Dynamically resolve paths based on selected season
PBP_DIR = os.path.join(RAW_DIR, selected_season, "pbp")
BOX_DIR = os.path.join(RAW_DIR, selected_season, "boxscores")
AGG_FILE = os.path.join(RAW_DIR, selected_season, "aggregate", "aggregate_season_latest.xlsx")

# 3. View Selector (Only defined once to avoid Streamlit Duplicate ID errors)
view = st.sidebar.radio("Navigate Views", ["Game Analyzer", "League & Season Trends", "Player Shooting Index"])


# ----------------- VIEW 1: GAME ANALYZER -----------------
if view == "Game Analyzer":
    st.title(f"Game Analyzer ({selected_season.replace('_', ' ')})")
    
    # Ensure raw directories exist
    os.makedirs(BOX_DIR, exist_ok=True)
    os.makedirs(PBP_DIR, exist_ok=True)
    
    games = load_all_game_options(BOX_DIR)
    
    if not games:
        st.info("No games loaded in raw folders. Please add your weekly boxscore/pbp Excel files to the directories.")
    else:
        selected_game = st.selectbox("Select Matchup", games, format_func=lambda g: g["name"])
        
        # Parse data
        team_summary, (t1_name, t1_players), (t2_name, t2_players) = parse_boxscore(selected_game["path"])
        
        # Attempt to find matching Play-by-Play file
        pbp_filename = selected_game["filename"].replace("boxscore_", "pbp_")
        pbp_path = os.path.join(PBP_DIR, pbp_filename)
        
        has_pbp = os.path.exists(pbp_path)
        if has_pbp:
            pbp_df, shot_zone_df, lineups_df = parse_pbp(pbp_path)
        
        # --- Subsection 1: Advanced Metrics (OER/DER/PACE) ---
        st.subheader("Team Efficiency Ratings")
        col1, col2, col3 = st.columns(3)
        
        # Safely parse variables from team summary
        t1_stats = team_summary.iloc[0]
        t2_stats = team_summary.iloc[1]
        
        with col1:
            st.metric(label="Possessions (Pace)", value=f"{t1_stats['POSScal']:.1f}")
        with col2:
            st.metric(label=f"{t1_name} OER / DER", value=f"{t1_stats['OERcal']:.1f} / {t1_stats['DERcal']:.1f}")
        with col3:
            st.metric(label=f"{t2_name} OER / DER", value=f"{t2_stats['OERcal']:.1f} / {t2_stats['DERcal']:.1f}")
            
        # --- Subsection 2: Accessible Four Factors Visual Comparison ---
        st.subheader("Four Factors Comparison")
        factors = ["eFG%", "TOV%cal", "ORB%cal", "FTR"]
        
        col_f1, col_f2 = st.columns(2)
        for i, factor in enumerate(factors):
            target_col = col_f1 if i % 2 == 0 else col_f2
            with target_col:
                # Plotly high-contrast horizontal bar chart comparing the two teams
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

        # --- Subsection 3: Boxscores ---
        st.subheader("Player Performance Profiles")
        team_tab1, team_tab2 = st.tabs([t1_name, t2_name])
        
        with team_tab1:
            st.dataframe(t1_players.style.format(precision=2), use_container_width=True)
        with team_tab2:
            st.dataframe(t2_players.style.format(precision=2), use_container_width=True)
            
        # --- Subsection 4: PBP-Specific Tabs ---
        if has_pbp:
            st.markdown("---")
            st.subheader("Game Flow and Lineups")
            pbp_tab, lineup_tab = st.tabs(["Shot Charts & Play Log", "Active Lineups Index"])
            
            with pbp_tab:
                # Shot location plotting and filtering
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
            st.warning("No matching Play-By-Play dataset found for this game. Upload corresponding PBP files into data directory.")


# ----------------- VIEW 2: LEAGUE & SEASON TRENDS -----------------
elif view == "League & Season Trends":
    st.title(f"League & Season Trends ({selected_season.replace('_', ' ')})")
    
    if not os.path.exists(AGG_FILE):
        st.info("No aggregate file found. Place your `aggregate_season_latest.xlsx` file in the correct directory.")
    else:
        offense_df, defense_df, master_players = parse_aggregate(AGG_FILE)
        
        tab_off, tab_def, tab_chart = st.tabs(["League Offense Leaderboard", "League Defense Leaderboard", "Rating Scatterplot"])
        
        with tab_off:
            st.write("Sorted League Efficiency (Offensive Metrics)")
            st.dataframe(offense_df.sort_values("OERcal", ascending=False).style.format(precision=2), use_container_width=True)
            
        with tab_def:
            st.write("Sorted League Efficiency (Defensive Metrics)")
            st.dataframe(defense_df.sort_values("DERcal", ascending=True).style.format(precision=2), use_container_width=True)
            
        with tab_chart:
            st.write("Offensive vs. Defensive Ratings Map")
            
            # Combine offense and defense to plot
            chart_data = offense_df[["Team", "OERcal"]].merge(defense_df[["Team", "DERcal"]], on="Team")
            
            # High-contrast colorblind-safe bubble chart
            fig_scat = px.scatter(
                chart_data,
                x="OERcal",
                y="DERcal",
                hover_name="Team",
                title="League Efficiency Quad Chart",
                labels={"OERcal": "Offensive Rating", "DERcal": "Defensive Rating"},
                color_discrete_sequence=[CB_BLUE]
            )
            
            # Add vertical and horizontal league means
            mean_oer = chart_data["OERcal"].mean()
            mean_der = chart_data["DERcal"].mean()
            fig_scat.add_vline(x=mean_oer, line_dash="dash", line_color=CB_ORANGE, annotation_text="Avg OER")
            fig_scat.add_hline(y=mean_der, line_dash="dash", line_color=CB_ORANGE, annotation_text="Avg DER")
            
            fig_scat.update_yaxes(autorange="reversed")  # Lower defensive rating is better!
            st.plotly_chart(fig_scat, use_container_width=True)


# ----------------- VIEW 3: PLAYER SHOOTING INDEX -----------------
elif view == "Player Shooting Index":
    st.title(f"Player Shooting Index ({selected_season.replace('_', ' ')})")
    
    if not os.path.exists(AGG_FILE):
        st.info("No aggregate files loaded. Please ensure seasonal player excel data is placed in the correct directories.")
    else:
        _, _, master_players = parse_aggregate(AGG_FILE)
        
        # Clean numeric profiles
        master_players["GamesPlayed"] = pd.to_numeric(master_players["GamesPlayed"], errors='coerce')
        master_players["PTS"] = pd.to_numeric(master_players["PTS"], errors='coerce')
        master_players["eFG%"] = pd.to_numeric(master_players["eFG%"], errors='coerce')
        
        st.write("Season aggregate player sorting engine. Ranked by eFG% or Volume.")
        
        # High contrast/accessible sort filter
        sort_metric = st.selectbox("Primary Sort Criteria", ["eFG%", "PTS", "GamesPlayed"])
        min_games = st.slider("Minimum Games Played Filter", 1, int(master_players["GamesPlayed"].max() or 20), 5)
        
        filtered_players = master_players[master_players["GamesPlayed"] >= min_games]
        sorted_players = filtered_players.sort_values(sort_metric, ascending=False)
        
        # Drop columns not needed for general view, keeping shooting splits
        view_cols = ["JUGADOR", "Team", "GamesPlayed", "PTS", "eFG%", "TS%", "Rim %", "Paint %", "MR %", "Cor3 %", "ATB3 %"]
        
        st.dataframe(
            sorted_players[view_cols].style.format({
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