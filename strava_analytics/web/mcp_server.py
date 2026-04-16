"""MCP server for ChatGPT connector integration.

Exposes athlete training data as MCP tools via the FastMCP framework.
Run standalone: strava-mcp <export_dir> [--port 8051]
ChatGPT connects via Settings > Apps & Connectors > Create connector
pointing to https://your-domain/mcp
"""

import argparse
import logging

from mcp.server.fastmcp import FastMCP

from strava_analytics.web import data
from strava_analytics.web.api_data import (
    get_fitness_summary,
    get_lifetime_stats,
    get_recent_activities,
    get_weekly_mileage,
    get_current_1rms,
    get_personal_records,
    get_detailed_runs,
    get_detailed_lifts,
    get_athlete_summary,
)

mcp = FastMCP("MERON", json_response=True)


def _df():
    return data.get_df()


@mcp.tool()
def get_fitness() -> dict:
    """Get current fitness metrics: CTL (fitness), ATL (fatigue), TSB (form), and status.
    Use this to understand the athlete's current training state."""
    return get_fitness_summary(_df())


@mcp.tool()
def get_stats() -> dict:
    """Get lifetime activity statistics: total activities, runs, lifts, miles, and date range."""
    return get_lifetime_stats(_df())


@mcp.tool()
def get_activities(days: int = 14, limit: int = 20) -> list[dict]:
    """Get recent activities with key metrics (distance, pace, HR, duration).
    Args:
        days: Number of days to look back (default 14)
        limit: Max activities to return (default 20)
    """
    return get_recent_activities(_df(), days=days, limit=limit)


@mcp.tool()
def get_mileage(weeks: int = 8) -> list[dict]:
    """Get weekly running mileage totals.
    Args:
        weeks: Number of weeks to return (default 8)
    """
    return get_weekly_mileage(_df(), weeks=weeks)


@mcp.tool()
def get_records() -> list[dict]:
    """Get personal records across standard distances (1mi, 5K, 10K, half marathon, marathon)."""
    return get_personal_records(_df())


@mcp.tool()
def get_strength() -> dict:
    """Get current estimated 1RM (one-rep max) for bench, squat, deadlift, and OHP in lbs."""
    return get_current_1rms(_df())


@mcp.tool()
def get_runs(limit: int = 30) -> list[dict]:
    """Get detailed run history with pace, HR, elevation, run type, and more.
    Args:
        limit: Max runs to return (default 30)
    """
    return get_detailed_runs(_df(), limit=limit)


@mcp.tool()
def get_lifts(limit: int = 20) -> list[dict]:
    """Get detailed lift session history with weights for bench, squat, deadlift, OHP.
    Args:
        limit: Max sessions to return (default 20)
    """
    return get_detailed_lifts(_df(), limit=limit)


@mcp.tool()
def get_summary() -> dict:
    """Get a complete overview of all athlete data in one call.
    Includes fitness, stats, recent activities, weekly mileage, strength, and PRs.
    Use this as the primary tool to get full context about the athlete."""
    return get_athlete_summary(_df())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="MERON MCP Server")
    parser.add_argument("export_dir", help="Path to Strava export directory")
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    data.init(args.export_dir)
    logging.info("MCP server starting on %s:%d/mcp", args.host, args.port)
    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
