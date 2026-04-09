"""Race predictions page — ozniai.com subpage pattern."""

import dash
import dash_bootstrap_components as dbc
from dash import html

from strava_analytics.web import data
from strava_analytics.web.components.layout import (
    hero_section, page_section, statement_section, feature_grid,
    numbered_card, product_card, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER,
)
from strava_analytics.predictions import (
    predict_race, compute_personal_exponent, RacePrediction,
)
from strava_analytics.vo2max import (
    compute_athlete_vdot, extract_race_efforts, compute_training_elevation,
)

# dash.register_page(__name__, path="/races", name="Race Predictions")


def _fmt(seconds: float) -> str:
    if seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_pace(seconds: float, distance_mi: float) -> str:
    if seconds <= 0 or distance_mi <= 0:
        return "--"
    pace_min = (seconds / 60) / distance_mi
    mins = int(pace_min)
    secs = int((pace_min - mins) * 60)
    return f"{mins}:{secs:02d} /mi"


def layout(**_kwargs):
    df = data.get_df()
    import pandas as pd

    now = df["date"].max()
    recent_cutoff = now - pd.Timedelta(days=180)

    # Critical Speed model from best efforts (replaces Kalman filter)
    from strava_analytics.critical_speed import (
        fit_critical_speed, predict_race_times, cs_to_vdot,
    )
    best_efforts_df = data.get_best_efforts()
    cs_params = fit_critical_speed(best_efforts_df)
    cs_vdot = cs_to_vdot(cs_params["cs_m_per_s"]) if cs_params["cs_m_per_s"] > 0 else 0

    # VDOT: prefer CS-derived, fall back to effort-based
    vdot = cs_vdot if cs_vdot > 0 else compute_athlete_vdot(df)
    all_efforts = extract_race_efforts(df)
    recent_efforts = [e for e in all_efforts
                      if e["date"] is not None and e["date"] >= recent_cutoff]

    training_elev = compute_training_elevation(df)
    training_alt_m = training_elev["mid_ft"] / 3.28084

    from strava_analytics.predictions import altitude_adjustment_peronnet
    alt_fraction = altitude_adjustment_peronnet(training_alt_m, acclimatized=True)

    recent_runs = df[(df["type"] == "Run") & (df["date"] >= now - pd.Timedelta(days=30))]
    current_avg_pace = recent_runs["pace_min_per_mi"].mean() if not recent_runs.empty else 10.0
    current_weekly_miles = recent_runs["distance_mi"].sum() / 4 if not recent_runs.empty else 17.0

    race_data = []
    seen_distances = set()
    for e in all_efforts:
        dist_km = round(e["distance_m"] / 1000, 1)
        bucket = round(dist_km / 2) * 2
        if bucket not in seen_distances and e["distance_m"] > 1500:
            race_data.append((e["distance_m"], e["time_s"]))
            seen_distances.add(bucket)
        if len(race_data) >= 5:
            break

    personal_exp = compute_personal_exponent(race_data) if len(race_data) >= 2 else 1.06

    # Calibration: use CS-predicted 5K time (from best efforts, not training runs)
    if cs_params["cs_m_per_s"] > 0:
        from strava_analytics.critical_speed import predict_time_cs
        cs_5k_s = predict_time_cs(cs_params["cs_m_per_s"], cs_params["d_prime_m"], 5000)
        calibration = {
            "distance_m": 5000,
            "time_s": cs_5k_s,
            "name": f"Critical Speed (R²={cs_params['r_squared']:.3f})",
            "elevation_gain_ft": 0,
        }
        calibration_label = calibration["name"]
    else:
        # Fallback to best recent 5K effort
        calibration = None
        for e in recent_efforts:
            if 4800 <= e["distance_m"] <= 5200:
                calibration = e
                break
        if not calibration:
            calibration = recent_efforts[0] if recent_efforts else None
        if not calibration:
            race_pace = current_avg_pace * 0.92
            est_5k_time = race_pace * 3.1 * 60
            calibration = {"distance_m": 5000, "time_s": est_5k_time,
                            "name": "est. from training pace", "elevation_gain_ft": 0}
        calibration_label = calibration.get("name", "recent effort")

    known_dist = calibration["distance_m"]
    known_time_raw = calibration["time_s"]

    cal_elev_gain = calibration.get("elevation_gain_ft", 0) or 0
    cal_dist_mi = known_dist / 1609.344

    from strava_analytics.predictions import elevation_gain_penalty_s
    elev_credit_s = elevation_gain_penalty_s(cal_elev_gain, cal_dist_mi)
    alt_credit_s = known_time_raw * (1 - alt_fraction) * 0.5
    known_time = known_time_raw - elev_credit_s - alt_credit_s

    bb_pred = predict_race(
        race_name="Boulder Bolder 10K",
        target_distance_m=10000, distance_label="10K",
        known_distance_m=known_dist, known_time_s=known_time,
        personal_exponent=personal_exp,
        race_altitude_m=1655, training_altitude_m=training_alt_m,
        elevation_gain_ft=272, vdot=vdot,
    )

    spartan_pred = predict_race(
        race_name="Spartan Beast \u2014 Running Portion",
        target_distance_m=21097, distance_label="13.1 mi",
        known_distance_m=known_dist, known_time_s=known_time,
        personal_exponent=personal_exp,
        race_altitude_m=1829, training_altitude_m=training_alt_m,
        elevation_gain_ft=3500, vdot=vdot,
    )

    avg_gain_per_mi = training_elev["avg_gain_per_mi"]

    return html.Div([
        # Hero
        hero_section(
            label="PREDICTIONS",
            headline="The math says you're faster than you think.",
            subtext=(
                f"Critical Speed {cs_params['cs_min_per_mi']:.1f} min/mi "
                f"(VDOT {cs_vdot:.1f}) at {training_elev['mid_ft']:.0f}ft. "
                f"Current pace: {current_avg_pace:.1f} min/mi at "
                f"{current_weekly_miles:.0f} mi/wk."
            ),
        ),

        # Calibration
        page_section("CALIBRATION", [
            feature_grid([
                numbered_card(1, "Critical Speed",
                              f"R\u00b2={cs_params['r_squared']:.3f} from {cs_params['n_points']} distances",
                              value=f"{cs_params['cs_min_per_mi']:.1f} /mi",
                              color=ACCENT),
                numbered_card(2, "5K (from CS)",
                              f"({calibration_label[:30]})",
                              value=_fmt(known_time_raw), color=ACCENT_SLATE),
                numbered_card(3, "Training Elevation",
                              f"{avg_gain_per_mi:.0f} ft/mi avg gain",
                              value=f"{training_elev['mid_ft']:,.0f} ft",
                              color=ACCENT_SLATE),
                numbered_card(4, "Current Fitness",
                              f"{current_weekly_miles:.0f} mi/wk (30d avg)",
                              value=f"{current_avg_pace:.1f} min/mi",
                              color=ACCENT_AMBER),
            ], columns=4),
        ]),

        # Target Races
        page_section("TARGET RACES", [
            dbc.Row([
                dbc.Col(_race_prediction_card(bb_pred, "May 25, 2026 \u2014 Boulder, CO"), md=6),
                dbc.Col(_spartan_card(spartan_pred), md=6),
            ], className="g-3"),
        ], alt_bg=True),

        # Statement
        statement_section(
            "THE CHALLENGE",
            "Two races. Five days apart. One is flat. "
            "One is a mountain covered in barbed wire.",
        ),

        # Equivalent Times
        page_section("EQUIVALENT RACE TIMES (FLAT, SEA LEVEL)", [
            _standard_predictions_table(known_dist, known_time, personal_exp, vdot),
        ], alt_bg=True),

        # Model Comparison
        page_section("MODEL COMPARISON \u2014 BOULDER BOLDER 10K", [
            _model_comparison(bb_pred),
        ]),

        # Best Efforts
        page_section("BEST RACE EFFORTS", [
            _efforts_table(all_efforts[:10]),
        ], alt_bg=True),

        # Methodology
        page_section("METHODOLOGY", [
            _methodology_section(),
        ]),

        # CTA
        cta_section(
            "Time to train for it.",
            "An 8-week plan built from your current fitness.",
            "Training Plan \u2192", "/plan",
        ),

        # Footer
        footer(),
    ])


def _race_prediction_card(pred: RacePrediction, subtitle: str) -> html.Div:
    return product_card(pred.race_name, [
        html.Div(subtitle, className="product-card__detail"),
        html.Div(
            _fmt(pred.predicted_low_s) + " \u2014 " + _fmt(pred.predicted_high_s),
            className="product-card__value",
        ),
        html.Div(
            f"Pace: {_fmt_pace(pred.predicted_low_s, pred.distance_m / 1609.344)} to "
            f"{_fmt_pace(pred.predicted_high_s, pred.distance_m / 1609.344)}",
            className="product-card__detail",
        ),
        html.Div(
            f"Alt. adj: {pred.altitude_adjustment_s:+.0f}s | "
            f"Elev. penalty: +{pred.elevation_penalty_s:.0f}s",
            className="product-card__detail",
            style={"marginTop": "8px"},
        ),
    ])


def _spartan_card(pred: RacePrediction) -> html.Div:
    obstacle_low = 30 * 90
    obstacle_high = 30 * 150
    total_low = pred.predicted_low_s + obstacle_low
    total_high = pred.predicted_high_s + obstacle_high

    return product_card("Spartan Beast", [
        html.Div("May 30-31, 2026 \u2014 Fort Carson, Colorado Springs",
                 className="product-card__detail"),
        html.Div(f"{_fmt(total_low)} \u2014 {_fmt(total_high)}",
                 className="product-card__value"),
        html.Div(
            f"Running: {_fmt(pred.predicted_low_s)} \u2014 {_fmt(pred.predicted_high_s)}",
            className="product-card__detail",
        ),
        html.Div(
            f"Obstacles (30): {_fmt(obstacle_low)} \u2014 {_fmt(obstacle_high)} est.",
            className="product-card__detail",
        ),
        html.Div(
            f"Elev. penalty: +{pred.elevation_penalty_s:.0f}s | "
            f"Expect 3,000-4,000ft total gain",
            className="product-card__detail",
            style={"marginTop": "8px"},
        ),
    ])


def _standard_predictions_table(known_dist, known_time, exponent, vdot):
    rows = []
    distances = [
        ("1 Mile", 1609.344), ("5K", 5000), ("10K", 10000),
        ("Half Marathon", 21097.5), ("Marathon", 42195),
    ]
    for name, dist in distances:
        pred = predict_race(name, dist, name, known_dist, known_time,
                            personal_exponent=exponent, vdot=vdot)
        pace = _fmt_pace(pred.predicted_low_s, dist / 1609.344)
        rows.append(html.Tr([
            html.Td(name, style={"fontWeight": "600"}),
            html.Td(_fmt(pred.riegel_time_s)),
            html.Td(_fmt(pred.riegel_personal_time_s)),
            html.Td(_fmt(pred.cameron_time_s)),
            html.Td(_fmt(pred.daniels_time_s)),
            html.Td(pace, style={"color": ACCENT_SLATE}),
        ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th("Distance"), html.Th("Riegel (1.06)"),
            html.Th(f"Riegel ({exponent:.2f})"),
            html.Th("Cameron"), html.Th("Daniels"), html.Th("Pace"),
        ])),
        html.Tbody(rows),
    ], className="table", style={
        "width": "100%", "borderCollapse": "collapse",
        "fontSize": "0.9rem", "marginBottom": "24px",
    })


def _model_comparison(pred: RacePrediction):
    models = [
        ("Riegel (standard)", pred.riegel_time_s),
        ("Riegel (personal)", pred.riegel_personal_time_s),
        ("Cameron", pred.cameron_time_s),
        ("Daniels VDOT", pred.daniels_time_s),
    ]
    items = []
    for name, time_s in models:
        items.append(html.Div([
            html.Span(f"{name}: ", style={"color": "var(--text-secondary)", "width": "180px",
                                           "display": "inline-block"}),
            html.Span(_fmt(time_s), style={"fontWeight": "600"}),
        ], style={"marginBottom": "4px", "fontSize": "0.9rem"}))

    items.append(html.Hr(style={"borderColor": "var(--border)", "margin": "8px 0"}))
    items.append(html.Div([
        html.Span("Altitude adjustment: ", style={"color": "var(--text-secondary)"}),
        html.Span(f"{pred.altitude_adjustment_s:+.0f}s", style={"fontWeight": "600"}),
    ], style={"fontSize": "0.9rem"}))
    items.append(html.Div([
        html.Span("Elevation penalty: ", style={"color": "var(--text-secondary)"}),
        html.Span(f"+{pred.elevation_penalty_s:.0f}s", style={"fontWeight": "600"}),
    ], style={"fontSize": "0.9rem"}))

    return html.Div(items, style={
        "backgroundColor": "var(--bg-card)", "padding": "16px",
        "border": "1px solid var(--border)", "marginBottom": "24px",
    })


def _efforts_table(efforts: list):
    if not efforts:
        return html.P("No race efforts found.", style={"color": "var(--text-muted)"})

    rows = []
    for e in efforts:
        rows.append(html.Tr([
            html.Td(e.get("name", "")[:40]),
            html.Td(f"{e['distance_m']/1000:.2f} km"),
            html.Td(_fmt(e["time_s"])),
            html.Td(f"{e['vdot']:.1f}", style={"color": ACCENT}),
            html.Td(e["date"].strftime("%b %d, %Y") if e.get("date") else ""),
        ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th("Name"), html.Th("Distance"), html.Th("Time"),
            html.Th("VDOT"), html.Th("Date"),
        ])),
        html.Tbody(rows),
    ], className="table", style={
        "width": "100%", "borderCollapse": "collapse",
        "fontSize": "0.85rem", "marginBottom": "24px",
    })


def _methodology_section():
    return html.Div([
        html.Details([
            html.Summary("Race Pace Models"),
            html.Ul([
                html.Li("Riegel (1981): T2 = T1 x (D2/D1)^1.06"),
                html.Li("Cameron (1999): Non-linear distance scaling model"),
                html.Li("Daniels VDOT (2014): VO2 cost + sustainable fraction model"),
                html.Li("Personal exponent computed from your race history via least-squares fit"),
            ], style={"fontSize": "0.8rem", "color": "var(--text-secondary)"}),
        ]),
        html.Details([
            html.Summary("Fitness-Aware Predictions"),
            html.Ul([
                html.Li("Banister exponential TRIMP (1991): physiologically-derived HR-lactate weighting"),
                html.Li("Kalman filter with CTL-informed drift: predictions decay when training drops "
                         "below Hickson threshold (70% of peak CTL)"),
                html.Li("Mujika & Padilla (2000): ~2.5%/week VO2max decay during detraining"),
                html.Li("Hickson (1985): no fitness loss if intensity maintained at reduced volume"),
                html.Li("VDOT staleness discount: older efforts weighted less when detraining detected"),
            ], style={"fontSize": "0.8rem", "color": "var(--text-secondary)"}),
        ]),
        html.Details([
            html.Summary("Altitude Adjustment"),
            html.Ul([
                html.Li("Peronnet et al. (1991): Acclimatized model"),
                html.Li("You train at ~5,800ft \u2014 racing at similar altitude = minimal adjustment"),
            ], style={"fontSize": "0.8rem", "color": "var(--text-secondary)"}),
        ]),
        html.Details([
            html.Summary("Elevation Gain Penalty"),
            html.Ul([
                html.Li("Adapted from Minetti et al. (2002)"),
                html.Li("~12 seconds per mile per 100ft of gain"),
            ], style={"fontSize": "0.8rem", "color": "var(--text-secondary)"}),
        ]),
    ], style={"fontSize": "0.9rem", "marginBottom": "24px"})
