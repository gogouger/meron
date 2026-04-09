"""ChatGPT integration — build context from athlete data and query OpenAI."""

import logging
from datetime import date, timedelta

import pandas as pd

from strava_analytics.web import data
from strava_analytics.metrics import format_pace
from strava_analytics.fitness import detect_prs
from strava_analytics.web.plan_data import get_current_fitness

logger = logging.getLogger(__name__)

_MAX_HISTORY = 10  # Keep last N message pairs for context


def build_system_prompt(df: pd.DataFrame) -> str:
    """Assemble a data context string for the ChatGPT system message.

    Includes current fitness, recent activities, PRs, strength, and plan summary.
    """
    sections = [
        "You are a personal fitness assistant for a runner and lifter. "
        "You have access to the athlete's training data below. Answer questions "
        "conversationally but precisely, using the data provided. If you're unsure, "
        "say so rather than guessing. Use imperial units (miles, lbs, feet).",
        "",
        "=== ATHLETE DATA ===",
    ]

    # Current fitness
    fitness = get_current_fitness(df)
    sections.append(
        f"\n## Current Fitness\n"
        f"- CTL (Fitness): {fitness['ctl']}\n"
        f"- ATL (Fatigue): {fitness['atl']}\n"
        f"- TSB (Form): {fitness['tsb']}\n"
        f"- Status: {fitness['label']}\n"
        f"- Date: {date.today().isoformat()}"
    )

    # Lifetime stats
    runs = df[df["type"] == "Run"]
    lifts = df[df["type"] == "Weight Training"]
    sections.append(
        f"\n## Lifetime Stats\n"
        f"- Total activities: {len(df)}\n"
        f"- Total runs: {len(runs)}\n"
        f"- Total lifts: {len(lifts)}\n"
        f"- Total miles: {df['distance_mi'].sum():.1f}\n"
        f"- Date range: {df['date'].min().strftime('%Y-%m-%d')} to {df['date'].max().strftime('%Y-%m-%d')}"
    )

    # Recent 2 weeks of activities
    now = df["date"].max()
    recent = df[df["date"] >= now - pd.Timedelta(days=14)].sort_values("date", ascending=False)
    if not recent.empty:
        lines = ["\n## Recent Activities (last 14 days)"]
        for _, row in recent.head(20).iterrows():
            act_type = row.get("type", "")
            name = row.get("name", act_type)
            d = row["date"].strftime("%Y-%m-%d")
            dist = row.get("distance_mi", 0)
            pace = row.get("pace_min_per_mi", 0)
            hr = row.get("avg_hr", 0)
            dur_s = row.get("moving_time_s", 0)

            parts = [f"- {d} | {act_type}: {name}"]
            if dist and not pd.isna(dist) and dist > 0:
                parts.append(f"{dist:.1f}mi")
            if pace and not pd.isna(pace) and pace > 0:
                parts.append(f"{format_pace(pace)}/mi")
            if hr and not pd.isna(hr):
                parts.append(f"HR {hr:.0f}")
            if dur_s and not pd.isna(dur_s) and dur_s > 0:
                m = int(dur_s // 60)
                parts.append(f"{m}min")
            lines.append(" | ".join(parts))
        sections.append("\n".join(lines))

    # Weekly mileage trend (last 8 weeks)
    if not runs.empty:
        lines = ["\n## Weekly Mileage (last 8 weeks)"]
        for i in range(8):
            start = now - pd.Timedelta(weeks=i + 1)
            end = now - pd.Timedelta(weeks=i)
            week_runs = runs[(runs["date"] > start) & (runs["date"] <= end)]
            miles = week_runs["distance_mi"].sum()
            week_label = start.strftime("%b %d")
            lines.append(f"- Week of {week_label}: {miles:.1f} mi")
        sections.append("\n".join(lines))

    # Current 1RMs
    for lift in ["bench", "squat", "deadlift", "ohp"]:
        col = f"{lift}_weight"
        if col in df.columns:
            vals = df[df[col].notna() & (df[col] > 0)][col]
            if not vals.empty:
                sections.append(f"- {lift.title()} recent max: {vals.iloc[-1]:.0f} lbs")

    # PRs / Best efforts
    efforts_df = data.get_best_efforts()
    prs = detect_prs(df, efforts_df)
    if prs:
        lines = ["\n## Personal Records"]
        for pr in prs:
            lines.append(
                f"- {pr['distance']}: {pr['best_time']} ({pr['best_pace']}/mi) "
                f"on {pr['best_date']}"
            )
        sections.append("\n".join(lines))

    return "\n".join(sections)


def get_data_context(df: pd.DataFrame, question: str) -> str:
    """Smart context selection based on the question topic.

    Returns a focused subset of data relevant to the question.
    """
    q = question.lower()
    extra = []

    # Running-specific
    if any(w in q for w in ["run", "pace", "mile", "5k", "10k", "marathon", "race",
                             "speed", "tempo", "interval", "long run"]):
        runs = df[df["type"] == "Run"].sort_values("date", ascending=False)
        if not runs.empty:
            lines = ["\n## Detailed Run Data (last 30 runs)"]
            for _, row in runs.head(30).iterrows():
                d = row["date"].strftime("%Y-%m-%d")
                dist = row.get("distance_mi", 0)
                pace = row.get("pace_min_per_mi", 0)
                hr = row.get("avg_hr", 0)
                elev = row.get("elevation_gain_ft", 0) or 0
                rtype = row.get("run_type", "")
                name = row.get("name", "")
                parts = [f"- {d} {name}"]
                if dist and not pd.isna(dist):
                    parts.append(f"{dist:.1f}mi")
                if pace and not pd.isna(pace):
                    parts.append(f"{format_pace(pace)}/mi")
                if hr and not pd.isna(hr):
                    parts.append(f"HR {hr:.0f}")
                if elev > 0:
                    parts.append(f"+{elev:.0f}ft")
                if rtype:
                    parts.append(f"[{rtype}]")
                lines.append(" | ".join(parts))
            extra.append("\n".join(lines))

    # Lifting-specific
    if any(w in q for w in ["lift", "bench", "squat", "deadlift", "ohp", "press",
                             "weight", "strength", "1rm", "pr"]):
        lifts_df = df[df["type"] == "Weight Training"].sort_values("date", ascending=False)
        if not lifts_df.empty:
            lines = ["\n## Recent Lift Sessions (last 20)"]
            for _, row in lifts_df.head(20).iterrows():
                d = row["date"].strftime("%Y-%m-%d")
                name = row.get("name", "Weight Training")
                parts = [f"- {d} {name}"]
                for lift in ["bench", "squat", "deadlift", "ohp"]:
                    w = row.get(f"{lift}_weight", None)
                    if w and not pd.isna(w) and w > 0:
                        parts.append(f"{lift.title()}: {w:.0f}lb")
                lines.append(" | ".join(parts))
            extra.append("\n".join(lines))

    return "\n".join(extra) if extra else ""


def ask_chatgpt(question: str, chat_history: list[dict],
                system_prompt: str, extra_context: str = "") -> str:
    """Call OpenAI API with context and return the response.

    Args:
        question: User's question.
        chat_history: List of {"role": "user"|"assistant", "content": str}.
        system_prompt: Pre-built system prompt with athlete data.
        extra_context: Additional context based on question topic.

    Returns:
        Assistant response text, or error message.
    """
    config = data.get_athlete_config()
    api_key = config.get("openai_api_key", "")

    if not api_key:
        return (
            "No OpenAI API key configured. Add your key in Settings or in "
            "`athlete_config.json` as `\"openai_api_key\": \"sk-...\"`"
        )

    try:
        from openai import OpenAI
    except ImportError:
        return (
            "The `openai` package is not installed. Run: "
            "`pip install openai` to enable the chat feature."
        )

    client = OpenAI(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]

    if extra_context:
        messages.append({
            "role": "system",
            "content": f"Additional context for this question:\n{extra_context}",
        })

    # Add recent chat history
    for msg in chat_history[-_MAX_HISTORY * 2:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": question})

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("OpenAI API error: %s", e)
        return f"Error calling OpenAI API: {e}"
