import plotly.graph_objects as go
import pandas as pd

def draw_boxscore_zone_charts(team_summary, t1_players, t2_players, t1_name, t2_name, selected_team, selected_player="All", *args, **kwargs):
    """
    Renders two side-by-side analytical horizontal bar charts of the 5 FIBA zones,
    pulling the exact pre-calculated data directly from the Boxscore files.
    """
    # Extraiem el paràmetre de lliga de manera segura de kwargs
    league_pps = kwargs.get("league_pps", 0.95)
    
    """
    Renders two side-by-side analytical horizontal bar charts of the 5 FIBA zones,
    pulling the exact pre-calculated data directly from the Boxscore files.
    """
    standard_zones = ["Rim", "Paint", "MR", "Cor3", "ATB3"]
    cat_labels = {
        "Rim": "A prop del cercle (Rim)",
        "Paint": "Pintura (Paint)",
        "MR": "Mitjana distància (MR)",
        "Cor3": "Triple cantonada (Corner 3)",
        "ATB3": "Triple frontal (ATB3)"
    }
    
    attempts = []
    pps_vals = []
    labels_display = [cat_labels[z] for z in standard_zones]
    
    # 1. AMB DOS EQUIPS COMBINATS (Tots els equips)
    if selected_team == "Tots els equips":
        t1_row = team_summary.iloc[0]
        t2_row = team_summary.iloc[1]
        
        for zone in standard_zones:
            fga1 = float(t1_row.get(f"{zone} FGA", 0.0))
            fgm1 = float(t1_row.get(f"{zone} FGM", 0.0))
            fga2 = float(t2_row.get(f"{zone} FGA", 0.0))
            fgm2 = float(t2_row.get(f"{zone} FGM", 0.0))
            
            total_fga = fga1 + fga2
            is_3pt = zone in ["Cor3", "ATB3"]
            pts1 = (3.0 * fgm1) if is_3pt else (2.0 * fgm1)
            pts2 = (3.0 * fgm2) if is_3pt else (2.0 * fgm2)
            total_pts = pts1 + pts2
            
            attempts.append(total_fga)
            pps = (total_pts / total_fga) if total_fga > 0 else 0.0
            pps_vals.append(pps)
            
        display_title_player = "Tots"
        
    # 2. EQUIPS INDIVIDUALS
    else:
        is_team_1 = (selected_team == t1_name)
        players_df = t1_players if is_team_1 else t2_players
        team_row = team_summary.iloc[0] if is_team_1 else team_summary.iloc[1]
        
        # Si el jugador és 'Tots', usem el total de l'equip
        if selected_player in ["All", "Tots"]:
            for zone in standard_zones:
                fga = float(team_row.get(f"{zone} FGA", 0.0))
                fgm = float(team_row.get(f"{zone} FGM", 0.0))
                is_3pt = zone in ["Cor3", "ATB3"]
                points = (3.0 * fgm) if is_3pt else (2.0 * fgm)
                
                attempts.append(fga)
                pps = (points / fga) if fga > 0 else 0.0
                pps_vals.append(pps)
            display_title_player = "Tots"
            
        # Si hi ha un jugador seleccionat, cerquem el seu registre individual
        else:
            player_rows = players_df[players_df["JUGADOR"] == selected_player]
            if player_rows.empty:
                attempts = [0] * 5
                pps_vals = [0.0] * 5
            else:
                p_row = player_rows.iloc[0]
                for zone in standard_zones:
                    fga = float(p_row.get(f"{zone} FGA", 0.0))
                    fgm = float(p_row.get(f"{zone} FGM", 0.0))
                    is_3pt = zone in ["Cor3", "ATB3"]
                    points = (3.0 * fgm) if is_3pt else (2.0 * fgm)
                    
                    attempts.append(fga)
                    pps = (points / fga) if fga > 0 else 0.0
                    pps_vals.append(pps)
            display_title_player = selected_player

    # --- Plotly Visualizations ---
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
        text=[f"{int(val)} tirs" for val in attempts],
        textposition='inside' if max(attempts or [0]) > 0 else 'outside'
    ))
    fig_vol.update_layout(
        title=f"Volum d'Intents per Zona - {display_title_player}",
        xaxis=dict(title="Número de tirs (Intents)", showgrid=True),
        yaxis=dict(autorange="reversed"),
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
    fig_pps.add_vline(
        x=league_pps, 
        line_dash="dash", 
        line_color="orange", 
        annotation_text=f"Mitjana de la Lliga ({league_pps:.2f} PPS)", 
        annotation_position="top right"
    )
    fig_pps.update_layout(
        title=f"Eficiència de Tir (Points Per Shot) - {display_title_player}",
        xaxis=dict(title="Punts per llançament (PPS)", showgrid=True, range=[0.0, 3.0]),
        yaxis=dict(autorange="reversed"),
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    return fig_vol, fig_pps
def draw_player_radar_charts(player_row, league_averages, league_max_fga):
    """
    Renders two side-by-side polar (radar) charts comparing a player's profile:
    1. Volume Profile (Average FGA per zone compared to league averages)
    2. Efficiency Profile (FG% per zone with total attempts displayed directly in axis labels)
    """
    # --- RÀDAR 1: GRÀFIC DE VOLUM DE TIRS (FGA) ---
    categories_vol = [
        "A prop del cercle (Rim)", 
        "Pintura (Paint)", 
        "Mitjana distància (MR)", 
        "Triple cantonada (Corner 3)", 
        "Triple frontal (ATB3)"
    ]
    categories_vol_closed = categories_vol + [categories_vol[0]]
    
    # Valors del jugador per partit (FGA)
    player_vol = [
        float(player_row.get("Rim FGA", 0.0)),
        float(player_row.get("Paint FGA", 0.0)),
        float(player_row.get("MR FGA", 0.0)),
        float(player_row.get("Cor3 FGA", 0.0)),
        float(player_row.get("ATB3 FGA", 0.0))
    ]
    player_vol.append(player_vol[0])
    
    # Mitjana de lliga de tirs intentats
    league_vol = [
        float(league_averages.get("Rim_FGA", 0.0)),
        float(league_averages.get("Paint_FGA", 0.0)),
        float(league_averages.get("MR_FGA", 0.0)),
        float(league_averages.get("Cor3_FGA", 0.0)),
        float(league_averages.get("ATB3_FGA", 0.0))
    ]
    league_vol.append(league_vol[0])
    
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Scatterpolar(
        r=league_vol, theta=categories_vol_closed, fill='toself',
        fillcolor='rgba(255, 127, 14, 0.15)', line=dict(color='#ff7f0e', width=2, dash='dash'),
        name="Mitjana Volum Lliga"
    ))
    fig_vol.add_trace(go.Scatterpolar(
        r=player_vol, theta=categories_vol_closed, fill='toself',
        fillcolor='rgba(31, 119, 180, 0.35)', line=dict(color='#1f77b4', width=3),
        name=player_row["JUGADOR"]
    ))
    
    max_fga_range = max([max(player_vol), max(league_vol), 1.0])
    fig_vol.update_layout(
        title="Volum d'Intents de Tir (FGA per Partit)",
        polar=dict(radialaxis=dict(visible=True, range=[0, max_fga_range])),
        showlegend=True, height=450, margin=dict(l=40, r=40, t=40, b=40)
    )

    # --- RÀDAR 2: GRÀFIC D'EFICIÈNCIA (% D'ENCERT AMB SÈRIES VISIBLES) ---
    # canvi: Modifiquem l'etiquetatge per fer visible el volum de tirs real del jugador i evitar enganys del 100%
    games_played = max(1.0, float(player_row.get("GamesPlayed", 1.0)))
    categories_eff = [
        f"Rim ({int(round(float(player_row.get('Rim FGA', 0.0)) * games_played))} tirs)",
        f"Paint ({int(round(float(player_row.get('Paint FGA', 0.0)) * games_played))} tirs)",
        f"MR ({int(round(float(player_row.get('MR FGA', 0.0)) * games_played))} tirs)",
        f"Corner 3 ({int(round(float(player_row.get('Cor3 FGA', 0.0)) * games_played))} tirs)",
        f"ATB3 ({int(round(float(player_row.get('ATB3 FGA', 0.0)) * games_played))} tirs)"
    ]
    categories_eff_closed = categories_eff + [categories_eff[0]]
    
    player_eff = [
        float(player_row.get("Rim %", 0.0)),
        float(player_row.get("Paint %", 0.0)),
        float(player_row.get("MR %", 0.0)),
        float(player_row.get("Cor3 %", 0.0)),
        float(player_row.get("ATB3 %", 0.0))
    ]
    player_eff.append(player_eff[0])
    
    league_eff = [
        float(league_averages.get("Rim_Pct", 0.0)),
        float(league_averages.get("Paint_Pct", 0.0)),
        float(league_averages.get("MR_Pct", 0.0)),
        float(league_averages.get("Cor3_Pct", 0.0)),
        float(league_averages.get("ATB3_Pct", 0.0))
    ]
    league_eff.append(league_eff[0])
    
    fig_eff = go.Figure()
    fig_eff.add_trace(go.Scatterpolar(
        r=league_eff, theta=categories_eff_closed, fill='toself',
        fillcolor='rgba(255, 127, 14, 0.15)', line=dict(color='#ff7f0e', width=2, dash='dash'),
        name="Mitjana % Lliga"
    ))
    fig_eff.add_trace(go.Scatterpolar(
        r=player_eff, theta=categories_eff_closed, fill='toself',
        fillcolor='rgba(31, 119, 180, 0.35)', line=dict(color='#1f77b4', width=3),
        name=player_row["JUGADOR"]
    ))
    
    fig_eff.update_layout(
        title="Eficiència d'Encert (% de l'Equip)",
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], ticksuffix="%")),
        showlegend=True, height=450, margin=dict(l=40, r=40, t=40, b=40)
    )
    
    return fig_vol, fig_eff
# Afegeix-ho a baix de tot de /utils/court_visualizer.py:
def draw_team_seasonal_zone_charts(offense_df, selected_team, league_pps=0.95):
    """
    Renders two side-by-side analytical horizontal bar charts of the 5 FIBA zones
    for a team's seasonal averages (Offensive Volume & Efficiency).
    """
    standard_zones = ["Rim", "Paint", "MR", "Cor3", "ATB3"]
    cat_labels = {
        "Rim": "A prop del cercle (Rim)",
        "Paint": "Pintura (Paint)",
        "MR": "Mitjana distància (MR)",
        "Cor3": "Triple cantonada (Corner 3)",
        "ATB3": "Triple frontal (ATB3)"
    }
    
    attempts = []
    pps_vals = []
    labels_display = [cat_labels[z] for z in standard_zones]
    
    # Busquem la fila de l'equip en les dades acumulades de lliga
    team_rows = offense_df[offense_df["Team"] == selected_team]
    if team_rows.empty:
        attempts = [0] * 5
        pps_vals = [0.0] * 5
    else:
        team_row = team_rows.iloc[0]
        for zone in standard_zones:
            # Extraguem la mitjana de llançaments intentats i encertats per partit
            fga = float(team_row.get(f"{zone} FGA", 0.0))
            fgm = float(team_row.get(f"{zone} FGM", 0.0))
            
            attempts.append(fga)
            is_3pt = zone in ["Cor3", "ATB3"]
            points = (3.0 * fgm) if is_3pt else (2.0 * fgm)
            pps = (points / fga) if fga > 0 else 0.0
            pps_vals.append(pps)
            
    # 1. Volume Chart
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Bar(
        y=labels_display,
        x=attempts,
        orientation='h',
        marker=dict(color=attempts, colorscale="Viridis", showscale=False),
        text=[f"{val:.1f} tirs/p" for val in attempts],
        textposition='inside' if max(attempts or [0]) > 0 else 'outside'
    ))
    fig_vol.update_layout(
        title=f"Volum d'Intents Mig per Partit - {selected_team}",
        xaxis=dict(title="Número de tirs mig (FGA)", showgrid=True),
        yaxis=dict(autorange="reversed"),
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    # 2. PPS Chart
    fig_pps = go.Figure()
    fig_pps.add_trace(go.Bar(
        y=labels_display,
        x=pps_vals,
        orientation='h',
        marker=dict(color=pps_vals, colorscale="Cividis", showscale=False),
        text=[f"{val:.2f} PPS" for val in pps_vals],
        textposition='inside' if max(pps_vals or [0.0]) > 0 else 'outside'
    ))
    fig_pps.add_vline(x=league_pps, line_dash="dash", line_color="orange", annotation_text=f"Mitjana de la Lliga ({league_pps:.2f} PPS)", annotation_position="top right")
    fig_pps.update_layout(
        title=f"Eficiència de Tir Miga (PPS) - {selected_team}",
        xaxis=dict(title="Punts per llançament (PPS)", showgrid=True, range=[0.0, 3.0]),
        yaxis=dict(autorange="reversed"),
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    return fig_vol, fig_pps