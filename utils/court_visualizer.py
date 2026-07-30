import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import plotly.colors as pcolors

def parse_coordinate(val):
    """Safely parses coordinates and handles European comma decimal notations."""
    if pd.isna(val):
        return None
    try:
        val_str = str(val).replace(",", ".").strip()
        return float(val_str)
    except ValueError:
        return None

def get_color_from_scale(val, min_val, max_val, scale_name="Viridis"):
    """
    Returns an rgba string for a value mapped to a named Plotly scale with 0.45 opacity.
    """
    if max_val == min_val:
        percent = 0.5
    else:
        percent = (val - min_val) / (max_val - min_val)
    percent = max(0.0, min(1.0, percent))
    
    scale = getattr(pcolors.sequential, scale_name, pcolors.sequential.Viridis)
    n_colors = len(scale)
    idx = percent * (n_colors - 1)
    idx_low = int(np.floor(idx))
    idx_high = int(np.ceil(idx))
    
    c_low = pcolors.hex_to_rgb(scale[idx_low]) if scale[idx_low].startswith("#") else pcolors.unlabel_rgb(scale[idx_low])
    c_high = pcolors.hex_to_rgb(scale[idx_high]) if scale[idx_high].startswith("#") else pcolors.unlabel_rgb(scale[idx_high])
    
    weight = idx - idx_low
    r = int(c_low[0] + (c_high[0] - c_low[0]) * weight)
    g = int(c_low[1] + (c_high[1] - c_low[1]) * weight)
    b = int(c_low[2] + (c_high[2] - c_low[2]) * weight)
    
    return f"rgba({r},{g},{b},0.45)"

def classify_zone_by_coords(x, y):
    """
    Classifies a shot into one of the 5 standard FIBA zones based on X/Y coordinates.
    Serves as a 100% bulletproof fallback if raw string categories do not match English names.
    """
    # Distance to hoop centered at (5.25, 25.0)
    dist_to_hoop = np.sqrt((x - 5.25)**2 + (y - 25.0)**2)
    
    # 1. Rim Area (Within 4.1 feet of hoop)
    if dist_to_hoop <= 4.1:
        return "Rim"
        
    # 2. Paint Area (Inside the key: X: 0 to 19, Y: 17 to 33)
    if 0 <= x <= 19.0 and 17.0 <= y <= 33.0:
        return "Paint"
        
    # 3. Corner 3 (X < 8.0 to make corners smaller/proportionate, and Y < 3 or Y > 47)
    if x < 8.0 and (y < 3.0 or y > 47.0):
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
        
    # Bilingual Mapping dictionary (Spanish, Catalan, and English)
    zone_mapping = {
        "rim": "Rim", "bajo aro": "Rim", "aro": "Rim", "sota canastra": "Rim", "sota l'aro": "Rim",
        "paint": "Paint", "zona": "Paint", "pintura": "Paint", "restricció": "Paint",
        "mid-range": "Mid-Range", "mr": "Mid-Range", "media distancia": "Mid-Range", "mig rang": "Mid-Range", "media-distancia": "Mid-Range",
        "corner 3": "Corner 3", "cor3": "Corner 3", "corner-3": "Corner 3", "triple esquina": "Corner 3", "triple-esquina": "Corner 3", "esquina": "Corner 3",
        "above the break 3": "Above the Break 3", "atb3": "Above the Break 3", "above-the-break 3": "Above the Break 3", "triple frontal": "Above the Break 3", "triple-frontal": "Above the Break 3", "frontal": "Above the Break 3"
    }
    
    # Parse coordinates first to allow coordinate fallback
    df["Parsed_X"] = df["Shot_X"].apply(parse_coordinate)
    df["Parsed_Y"] = df["Shot_Y"].apply(parse_coordinate)
    df = df[df["Parsed_X"].notna() & df["Parsed_Y"].notna()].copy()
    
    if df.empty:
        return df, {}
        
    # Map by String first, fallback to Coordinate Classifier if unmapped
    df["Clean_Zone"] = df["Shot_Zone"].astype(str).str.lower().str.strip().map(zone_mapping)
    
    # Apply the bulletproof coordinate classifier for any unmapped rows (e.g. if Rim was 0)
    unmapped_mask = df["Clean_Zone"].isna()
    if unmapped_mask.any():
        df.loc[unmapped_mask, "Clean_Zone"] = df[unmapped_mask].apply(
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
    Renders two side-by-side shot charts on a side-facing FIBA half-court.
    Background zones are mathematically disjoint to prevent tooltip overlaps.
    """
    df, stats_dict = get_zone_stats(pbp_df, selected_player)
    
    st_player_label = "Tots" if not selected_player or selected_player == "All" else selected_player
    
    if df.empty:
        fig_vol = go.Figure()
        fig_vol.add_annotation(text="No s'han trobat coordenades de tir per a aquesta selecció", showarrow=False, font=dict(size=14))
        fig_vol.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), height=400)
        return fig_vol, fig_vol

    # Programmatic FIBA side-court arc points (R=22.15, hoop centered lateral at Y=25)
    theta_limit = np.arcsin(22.0 / 22.15)
    arc_angles = np.linspace(-theta_limit, theta_limit, 100)
    arc_x = 5.25 + 22.15 * np.cos(arc_angles)
    arc_y = 25.0 + 22.15 * np.sin(arc_angles)
    
    hoop_angles = np.linspace(0, 2*np.pi, 50)
    hoop_x = 5.25 + 0.75 * np.cos(hoop_angles)
    hoop_y = 25.0 + 0.75 * np.sin(hoop_angles)
    
    ft_angles = np.linspace(-np.pi/2, np.pi/2, 50)
    ft_x = 19.0 + 6.0 * np.cos(ft_angles)
    ft_y = 25.0 + 6.0 * np.sin(ft_angles)

    volumes = [stats_dict.get(z, {}).get("Attempts", 0) for z in stats_dict]
    pps_values = [stats_dict.get(z, {}).get("PPS", 0.0) for z in stats_dict]
    
    min_vol, max_vol = min(volumes or [0]), max(volumes or [1])
    min_pps, max_pps = min(pps_values or [0.0]), max(pps_values or [1.0])

    # Disjoint polygon layout (Corner 3 width reduced to X=8.0; ATB3 base starts at X=8.0)
    zone_polygons = {
        "Corner 3": [
            {"x": [0, 8, 8, 0, 0], "y": [-3, -3, 3, 3, -3]},      # Bottom Corner (X reduït a 8.0)
            {"x": [0, 8, 8, 0, 0], "y": [47, 47, 53, 53, 47]}     # Top Corner (X reduït a 8.0)
        ],
        "Above the Break 3": [
            # ATB3 base starts at X=8.0, eliminating overlaps with Corner 3 on tooltip hover
            {"x": [8, 47, 47, 8, 8] + list(arc_x[::-1]) + [8], 
             "y": [-3, -3, 53, 53, 47] + list(arc_y[::-1]) + [-3]}
        ],
        "Mid-Range": [
            {"x": [0] + list(arc_x) + [0, 0], "y": [3] + list(arc_y) + [47, 3]}
        ],
        "Paint": [
            {"x": [0, 19, 19, 0, 0], "y": [17, 17, 33, 33, 17]}
        ],
        "Rim": [
            {"x": list(5.25 + 4.1 * np.cos(hoop_angles)), "y": list(25.0 + 4.1 * np.sin(hoop_angles))}
        ]
    }

    figs = []
    for metric_name, min_v, max_v, scale in [("Attempts", min_vol, max_vol, "Viridis"), ("PPS", min_pps, max_pps, "Cividis")]:
        fig = go.Figure()
        
        # 1. Draw Filled Background Polygons (Choropleth Background)
        for zone_name, polys in zone_polygons.items():
            val = stats_dict.get(zone_name, {}).get(metric_name, 0.0)
            color_str = get_color_from_scale(val, min_v, max_v, scale)
            
            for poly in polys:
                fig.add_trace(go.Scatter(
                    x=poly["x"],
                    y=poly["y"],
                    fill="toself",
                    fillcolor=color_str,
                    line=dict(color="rgba(0,0,0,0)"),
                    mode="lines",
                    hoverinfo="text",
                    text=f"Zona: {zone_name}<br>Intents: {stats_dict.get(zone_name, {}).get('Attempts', 0)}<br>PPS: {stats_dict.get(zone_name, {}).get('PPS', 0.0):.2f}",
                    showlegend=False
                ))

        # 2. Draw Official FIBA Court Lines on top of colors
        court_lines = [
            go.Scatter(x=[0, 47, 47, 0, 0], y=[0, 0, 50, 50, 0], mode="lines", line=dict(color="darkgray", width=1.5), showlegend=False),
            go.Scatter(x=[0, 19, 19, 0], y=[17, 17, 33, 33], mode="lines", line=dict(color="darkgray", width=1.5), showlegend=False),
            go.Scatter(x=ft_x, y=ft_y, mode="lines", line=dict(color="darkgray", width=1.5), showlegend=False),
            go.Scatter(x=[4, 4], y=[22, 28], mode="lines", line=dict(color="darkgray", width=2.5), showlegend=False),
            go.Scatter(x=hoop_x, y=hoop_y, mode="lines", line=dict(color="darkgray", width=2), showlegend=False),
            go.Scatter(x=[0.0] + list(arc_x) + [0.0], y=[3.0] + list(arc_y) + [47.0], mode="lines", line=dict(color="darkgray", width=1.5), showlegend=False)
        ]
        for line in court_lines:
            fig.add_trace(line)

        # 3. Plot Individual Shots (Encistellats vs Errats)
        df["IsMade"] = df["Play_Result"].apply(lambda r: "Encistellats" if "Missed" not in str(r) else "Errats")
        
        for result, color, symbol in [("Encistellats", "#2ca02c", "circle"), ("Errats", "#d62728", "x")]:
            sub_df = df[df["IsMade"] == result]
            fig.add_trace(go.Scatter(
                x=sub_df["Parsed_X"],
                y=sub_df["Parsed_Y"],
                mode="markers",
                marker=dict(color=color, size=6, symbol=symbol),
                name=result,
                hoverinfo="text",
                text=sub_df["text"]
            ))

        # 4. Hidden Dummy Trace to Force a Colored Scale Legend
        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(
                colorscale=scale,
                cmin=min_v,
                cmax=max_v,
                showscale=True,
                colorbar=dict(
                    title=dict(
                        text="PPS (Punts per Tir)" if metric_name == "PPS" else "Intents de Tir",
                        side="top"
                    ),
                    thickness=15,
                    x=1.02,
                    y=0.5,
                    ypad=10
                )
            ),
            showlegend=False
        ))

        # Visual layout settings
        title_prefix = "Volum de Tirs" if metric_name == "Attempts" else "Eficiència de Tir (PPS)"
        fig.update_layout(
            title=f"{title_prefix} - {st_player_label}",
            xaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-2, 49]),
            # Visual aspect ratios locked strictly
            yaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-3, 53], scaleanchor="x", scaleratio=1),
            plot_bgcolor="white",
            height=500,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        figs.append(fig)
        
    return figs[0], figs[1]