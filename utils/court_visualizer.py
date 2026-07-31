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

def classify_zone_by_coords(x, y):
    """
    Classifies a shot into one of the 5 standard FIBA zones based on X/Y coordinates.
    Using physical coordinates is 100% robust against manual tracking labeling errors.
    """
    # Distance to hoop centered at (5.25, 25.0)
    dist_to_hoop = np.sqrt((x - 5.25)**2 + (y - 25.0)**2)
    
    # 1. Rim Area (Within 4.1 feet of hoop)
    if dist_to_hoop <= 4.1:
        return "Rim"
        
    # 2. Paint Area (Inside the key: X: 0 to 19, Y: 17 to 33)
    if 0 <= x <= 19.0 and 17.0 <= y <= 33.0:
        return "Paint"
        
    # 3. Corner 3 (X < 9.8 to match exactly the 2.99m FIBA corner rule, and Y < 3 or Y > 47)
    if x < 9.8 and (y < 3.0 or y > 47.0):
        return "Corner 3"
        
    # 4. Above the Break 3 (Outside 3pt arc: distance to hoop > 22.15)
    if dist_to_hoop > 22.15:
        return "Above the Break 3"
        
    # 5. Mid-Range (Default: inside 3pt arc, outside Paint/Rim)
    return "Mid-Range"

def get_zone_stats(pbp_df, selected_player=None):
    """Calculates shot counts and average points per shot (PPS) per zone."""
    if selected_player and selected_player != "All":
        df = pbp_df[pbp_df["Player"] == selected_player].copy()
    else:
        df = pbp_df.copy()
        
    df["Parsed_X"] = df["Shot_X"].apply(parse_coordinate)
    df["Parsed_Y"] = df["Shot_Y"].apply(parse_coordinate)
    df = df[df["Parsed_X"].notna() & df["Parsed_Y"].notna()].copy()
    
    if df.empty:
        return df, {}
        
    # Always classify by coordinates to guarantee 100% accurate zone counts
    df["Clean_Zone"] = df.apply(
        lambda row: classify_zone_by_coords(row["Parsed_X"], row["Parsed_Y"]), axis=1
    )
        
    df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0)
    
    # Group by zone to get Volume and PPS
    zone_groups = df.groupby("Clean_Zone").agg(
        Attempts=("Clean_Zone", "count"),
        Total_Points=("Points", "sum")
    ).reset_index()
    
    zone_groups["PPS"] = zone_groups["Total_Points"] / zone_groups["Attempts"]
    stats_dict = zone_groups.set_index("Clean_Zone").to_dict(orient="index")
    
    return df, stats_dict

def draw_colorblind_shot_charts(pbp_df, selected_player=None):
    """
    Renders two side-by-side analytical horizontal bar charts of the 5 FIBA zones:
    1. Volume Chart (Attempts in Zone)
    2. PPS Chart (Points Per Shot in Zone)
    """
    df, stats_dict = get_zone_stats(pbp_df, selected_player)
    
    st_player_label = "Tots" if not selected_player or selected_player == "All" else selected_player
    
    # Empty state fallback
    if df.empty:
        fig_empty = go.Figure()
        fig_empty.add_annotation(text="No s'han trobat llançaments per a aquesta selecció", showarrow=False, font=dict(size=14))
        fig_empty.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), height=350)
        return fig_empty, fig_empty

    # Ordered list from closest-to-rim to furthest-from-rim
    standard_zones = ["Rim", "Paint", "Mid-Range", "Corner 3", "Above the Break 3"]
    
    # Catalan display translation labels
    cat_labels = {
        "Rim": "A prop del cercle (Rim)",
        "Paint": "Pintura (Paint)",
        "Mid-Range": "Mitjana distància (MR)",
        "Corner 3": "Triple cantonada (Corner 3)",
        "Above the Break 3": "Triple frontal (ATB3)"
    }
    
    attempts = []
    pps_vals = []
    labels_display = []
    
    for zone in standard_zones:
        stats = stats_dict.get(zone, {"Attempts": 0, "PPS": 0.0})
        attempts.append(stats["Attempts"])
        pps_vals.append(stats["PPS"])
        labels_display.append(cat_labels[zone])

    # 1. Volume Chart (Viridis)
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Bar(
        y=labels_display,
        x=attempts,
        orientation='h',
        marker=dict(
            color=attempts,
            colorscale="Viridis",
            showscale=False
        ),
        text=[f"{val} tirs" for val in attempts],
        textposition='inside' if max(attempts or [0]) > 0 else 'outside'
    ))
    fig_vol.update_layout(
        title=f"Volum d'Intents per Zona - {st_player_label}",
        xaxis=dict(title="Número de tirs (Intents)", showgrid=True),
        yaxis=dict(autorange="reversed"), # Rim dalt de tot, ATB3 a sota
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    # 2. PPS Chart (Cividis)
    fig_pps = go.Figure()
    fig_pps.add_trace(go.Bar(
        y=labels_display,
        x=pps_vals,
        orientation='h',
        marker=dict(
            color=pps_vals,
            colorscale="Cividis",
            showscale=False
        ),
        text=[f"{val:.2f} PPS" for val in pps_vals],
        textposition='inside' if max(pps_vals or [0.0]) > 0 else 'outside'
    ))
    # canvi: Línia discontínua a 1.0 PPS de referència per a l' staff
    fig_pps.add_vline(x=1.0, line_dash="dash", line_color="orange", annotation_text="Eficiència Estàndard (1.0 PPS)", annotation_position="top right")
    fig_pps.update_layout(
        title=f"Eficiència de Tir (Points Per Shot) - {st_player_label}",
        xaxis=dict(title="Punts per llançament (PPS)", showgrid=True, range=[0.0, 3.0]),
        yaxis=dict(autorange="reversed"),
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    return fig_vol, fig_pps