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
    Renders two side-by-side shot charts on a side-facing FIBA half-court.
    Uses programmatic coordinate traces instead of layout shapes to prevent distortions.
    """
    df, stats_dict = get_zone_stats(pbp_df, selected_player)
    
    # Clean player label fallback for Catalan
    st_player_label = "Tots" if not selected_player or selected_player == "All" else selected_player
    
    if df.empty:
        fig_vol = go.Figure()
        fig_vol.add_annotation(text="No s'han trobat coordenades de tir per a aquesta selecció", showarrow=False, font=dict(size=14))
        fig_vol.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), height=400)
        return fig_vol, fig_vol
        
    # 1. Volume Chart
    fig_vol = px.scatter(
        df,
        x="Parsed_X",
        y="Parsed_Y",
        color="Zone_Attempts",
        color_continuous_scale="Viridis",
        labels={"Zone_Attempts": "Intents a la Zona"},
        title=f"Volum de Tirs per Zona - {st_player_label}",
        hover_data={"Parsed_X": False, "Parsed_Y": False, "Clean_Zone": True, "Zone_Attempts": True, "time": True}
    )
    
    # 2. PPS Chart
    fig_pps = px.scatter(
        df,
        x="Parsed_X",
        y="Parsed_Y",
        color="Zone_PPS",
        color_continuous_scale="Cividis",
        labels={"Zone_PPS": "Punts per Tir (PPS)"},
        title=f"Eficiència de Tir (PPS) per Zona - {st_player_label}",
        hover_data={"Parsed_X": False, "Parsed_Y": False, "Clean_Zone": True, "Zone_PPS": ":.2f", "time": True}
    )
    
    # --- FIBA Side-Facing Court Coordinate Calculation ---
    # Basket center is at (5.25, 25).
    # Radius of 3-point arc is 22.15 feet (6.75 meters).
    # Calculations for straight 3-point lines joining corner arcs cleanly:
    theta_limit = np.arcsin(22.0 / 22.15)
    arc_angles = np.linspace(-theta_limit, theta_limit, 100)
    arc_x = 5.25 + 22.15 * np.cos(arc_angles)
    arc_y = 25.0 + 22.15 * np.sin(arc_angles)
    
    # Hoop circle trace
    hoop_angles = np.linspace(0, 2*np.pi, 50)
    hoop_x = 5.25 + 0.75 * np.cos(hoop_angles)
    hoop_y = 25.0 + 0.75 * np.sin(hoop_angles)
    
    # Free throw semi-circle trace
    ft_angles = np.linspace(-np.pi/2, np.pi/2, 50)
    ft_x = 19.0 + 6.0 * np.cos(ft_angles)
    ft_y = 25.0 + 6.0 * np.sin(ft_angles)

    court_traces = [
        # Outer boundary lines (Rectangle)
        go.Scatter(x=[0, 47, 47, 0, 0], y=[0, 0, 50, 50, 0], mode="lines", line=dict(color="lightgray", width=1.5), showlegend=False),
        # Restricted Key/Paint Area
        go.Scatter(x=[0, 19, 19, 0], y=[17, 17, 33, 33], mode="lines", line=dict(color="lightgray", width=1.5), showlegend=False),
        # Free-throw semi-circle
        go.Scatter(x=ft_x, y=ft_y, mode="lines", line=dict(color="lightgray", width=1.5), showlegend=False),
        # Backboard line
        go.Scatter(x=[4, 4], y=[22, 28], mode="lines", line=dict(color="lightgray", width=2.5), showlegend=False),
        # Hoop/Rim
        go.Scatter(x=hoop_x, y=hoop_y, mode="lines", line=dict(color="lightgray", width=2), showlegend=False),
        # 3-Point Arc Line (Cantonades rectes + arc perfectament calculats)
        go.Scatter(x=[0.0] + list(arc_x) + [0.0], y=[3.0] + list(arc_y) + [47.0], mode="lines", line=dict(color="lightgray", width=1.5), showlegend=False)
    ]
    
    for fig in [fig_vol, fig_pps]:
        # Add all visual court traces to the plot
        for trace in court_traces:
            fig.add_trace(trace)
            
        # Update layout and BLOCK ASPECT RATIO so the court never stretches
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-1, 48]),
            yaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-1, 51], scaleanchor="x", scaleratio=1),
            plot_bgcolor="white",
            height=500,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        
    return fig_vol, fig_pps