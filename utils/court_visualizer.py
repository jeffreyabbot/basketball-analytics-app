import plotly.graph_objects as go
import pandas as pd

def draw_boxscore_zone_charts(team_summary, t1_players, t2_players, t1_name, t2_name, selected_team, selected_player="All"):
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
    fig_pps.add_vline(x=1.0, line_dash="dash", line_color="orange", annotation_text="Eficiència Estàndard (1.0 PPS)", annotation_position="top right")
    fig_pps.update_layout(
        title=f"Eficiència de Tir (Points Per Shot) - {display_title_player}",
        xaxis=dict(title="Punts per llançament (PPS)", showgrid=True, range=[0.0, 3.0]),
        yaxis=dict(autorange="reversed"),
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    return fig_vol, fig_pps