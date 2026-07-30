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

def get_zone_stats(pbp_df, selected_player=None):
    """Calculates shot counts and average points per shot (PPS) per zone."""
    if selected_player and selected_player != "All":
        df = pbp_df[pbp_df["Player"] == selected_player].copy()
    else:
        df = pbp_df.copy()
        
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
    stats_dict = zone_groups.set_index("Clean_Zone").to_dict(orient="index")
    
    return df, stats_dict

def draw_colorblind_shot_charts(pbp_df, selected_player=None):
    """
    Renders two side-by-side shot charts on a side-facing FIBA half-court.
    Fills background zones programmatically to prevent any visual gaps.
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

    # Dynamic filled polygons extending slightly beyond [0, 50] to contain minor tracking offsets
    zone_polygons = {
        "Corner 3": [
            {"x": [0, 14, 14, 0, 0], "y": [-3, -3, 3, 3, -3]},      # Bottom Corner (Y estès a -3)
            {"x": [0, 14, 14, 0, 0], "y": [47, 47, 53, 53, 47]}     # Top Corner (Y estès a 53)
        ],
        "Above the Break 3": [
            # Closed polygon covering the entire 3pt space with no gaps
            {"x": [0, 0, 47, 47, 0, 0] + list(arc_x[::-1]) + [0], 
             "y": [3, -3, -3, 53, 53, 47] + list(arc_y[::-1]) + [3]}
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
        
        # 1. Draw Filled Background Polygons
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

        # 2. Draw Official FIBA Court Lines (Exactly at Y=0 and Y=50)
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

        # 4. Hidden Dummy Trace to Force a Colored scale Legend on the Right Side
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
                    title="Punts per Tir" if metric_name == "PPS" else "Intents de Tir",
                    thickness=15,
                    x=1.02,
                    y=0.5,
                    ypad=10,
                    titleside="top"
                )
            ),
            showlegend=False
        ))

        # Visual layout settings
        title_prefix = "Volum de Tirs" if metric_name == "Attempts" else "Eficiència de Tir (PPS)"
        fig.update_layout(
            title=f"{title_prefix} - {st_player_label}",
            xaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-2, 49]),
            # Range de visualització tancat per evitar deformacions en pantalles amples
            yaxis=dict(showgrid=False, zeroline=False, visible=False, range=[-3, 53], scaleanchor="x", scaleratio=1),
            plot_bgcolor="white",
            height=500,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        figs.append(fig)
        
    return figs[0], figs[1]