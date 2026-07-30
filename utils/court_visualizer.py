import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

def draw_colorblind_shot_chart(pbp_df, selected_player=None):
    """
    Generates a colorblind-friendly (Cividis/Viridis scale) Plotly interactive shot chart.
    Coordinates are assumed to be standard half-court boundaries.
    """
    # Filter by player if requested
    if selected_player and selected_player != "All":
        pbp_df = pbp_df[pbp_df["Player"] == selected_player]
        
    # Keep only plays with physical coordinates
    shots = pbp_df[pbp_df["Shot_X"].notna() & pbp_df["Shot_Y"].notna()].copy()
    
    if shots.empty:
        # Return empty placeholder figure with a note
        fig = go.Figure()
        fig.add_annotation(text="No shot coordinates found for this selection", showarrow=False, font=dict(size=16))
        return fig
    
    # Map play results to marker shapes/symbols for high non-color contrast
    shots["IsMade"] = shots["Play_Result"].apply(lambda r: "Made" if "Missed" not in str(r) else "Missed")
    shots["Symbol"] = shots["IsMade"].apply(lambda m: "circle" if m == "Made" else "x")
    
    # Draw shots using Cividis (safe for deuteranopia, protanopia, and tritanopia)
    fig = px.scatter(
        shots,
        x="Shot_X",
        y="Shot_Y",
        color="Shot_Zone",
        symbol="IsMade",
        hover_data=["time", "quarter", "text"],
        color_discrete_sequence=px.colors.qualitative.Safe, # Optimized palette
        title="Shot Locations Map"
    )
    
    # Draw standard baseline/rim boundaries (Simplified half-court mapping coordinates)
    # Adjust outer bounds to match your coordinate boundaries (typically width: 0-50, length: 0-47 in feet)
    fig.add_shape(type="rect", x0=0, y0=0, x1=50, y1=47, line=dict(color="gray", width=1)) # Half-court boundary
    fig.add_shape(type="circle", x0=21, y0=4, x1=29, y1=12, line=dict(color="gray", width=1)) # Rim area hoop
    
    fig.update_layout(
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        width=600,
        height=550,
        plot_bgcolor="white"
    )
    return fig