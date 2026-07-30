import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

def parse_coordinate(val):
    """Safely parses coordinates and handles European comma decimal notations."""
    if pd.isna(val):
        return None
    try:
        val_str = str(val).replace(",", ".").strip()
        return float(val_str)
    except ValueError:
        return None

def get_zone_stats(pbp_df, selected_player=None):
    """Calculates shot counts and average points per shot (PPS) per zone."""
    if selected_player and selected_player != "All":
        df = pbp_df[pbp_df["Player"] == selected_player].copy()
    else:
        df = pbp_df.copy()
        
    # Standardize Shot_Zone names
    zone_mapping = {
        "rim": "Rim",
        "paint": "Paint",
        "mid-range": "Mid-Range",
        "mr": "Mid-Range",
        "corner 3": "Corner 3",
        "cor3": "Corner 3",
        "corner-3": "Corner 3",
        "above the break 3": "Above the Break 3",
        "atb3": "Above the Break 3",
        "above-the-break 3": "Above the Break 3"
    }
    
    df["Clean_Zone"] = df["Shot_Zone"].astype(str).str.lower().str.strip().map(zone_mapping).fillna(df["Shot_Zone"])
    
    # Parse points and coordinates
    df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0)
    df["Parsed_X"] = df["Shot_X"].apply(parse_coordinate)
    df["Parsed_Y"] = df["Shot_Y"].apply(parse_coordinate)
    
    # Drop rows without coordinates
    df = df[df["Parsed_X"].notna() & df["Parsed_Y"].notna()].copy()
    
    if df.empty:
        return df, {}
        
    # Group by zone to get Volume and PPS
    zone_groups = df.groupby("Clean_Zone").agg(
        Attempts=("Clean_Zone", "count"),
        Total_Points=("Points", "sum")
    ).reset_index()
    
    zone_groups["PPS"] = zone_groups["Total_Points"] / zone_groups["Attempts"]
    
    # Create lookup dict
    stats_dict = zone_groups.set_index("Clean_Zone").to_dict(orient="index")
    
    # Map back to individual shots
    df["Zone_Attempts"] = df["Clean_Zone"].map(lambda z: stats_dict.get(z, {}).get("Attempts", 0))
    df["Zone_PPS"] = df["Clean_Zone"].map(lambda z: stats_dict.get(z, {}).get("PPS", 0.0))
    
    return df, stats_dict

def draw_colorblind_shot_charts(pbp_df, selected_player=None):
    """
    Renders two side-by-side shot charts using colorblind-safe color scales:
    1. Volume Chart (Attempts in Zone)
    2. PPS Chart (Points Per Shot in Zone)
    """
    df, stats_dict = get_zone_stats(pbp_df, selected_player)
    
    if df.empty:
        fig_vol = go.Figure()
        fig_vol.add_annotation(text="No shot coordinates found for this selection", showarrow=False, font=dict(size=14))
        fig_vol.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), height=400)
        return fig_vol, fig_vol
        
    # 1. Volume Chart (sequential Viridis)
    fig_vol = px.scatter(
        df,
        x="Parsed_X",
        y="Parsed_Y",
        color="Zone_Attempts",
        color_continuous_scale="Viridis",
        labels={"Zone_Attempts": "Attempts in Zone"},
        title="Shot Volume by Zone",
        hover_data={"Parsed_X": False, "Parsed_Y": False, "Clean_Zone": True, "Zone_Attempts": True, "time": True}
    )
    
    # 2. PPS Chart (sequential Cividis)
    fig_pps = px.scatter(
        df,
        x="Parsed_X",
        y="Parsed_Y",
        color="Zone_PPS",
        color_continuous_scale="Cividis",
        labels={"Zone_PPS": "Points Per Shot (PPS)"},
        title="Shot Efficiency (PPS) by Zone",
        hover_data={"Parsed_X": False, "Parsed_Y": False, "Clean_Zone": True, "Zone_PPS": ":.2f", "time": True}
    )
    
    # Draw standard baseline/rim boundaries on half-court
    for fig in [fig_vol, fig_pps]:
        fig.add_shape(type="rect", x0=0, y0=0, x1=50, y1=47, line=dict(color="lightgray", width=1.5))
        fig.add_shape(type="circle", x0=22, y0=4.25, x1=28, y1=10.25, line=dict(color="lightgray", width=1.5))
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, visible=False),
            yaxis=dict(showgrid=False, zeroline=False, visible=False),
            plot_bgcolor="white",
            height=450,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        
    return fig_vol, fig_pps