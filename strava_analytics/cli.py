"""CLI entry point for Strava analytics."""

import argparse

import pandas as pd
from tabulate import tabulate

from .api.context import current_user_id
from .loader import load_activities, load_profile
from .enrichment import enrich
from . import metrics


def _db_init():
    """Lazy-initialize the DB + migrations. Returns (engine, session_factory)."""
    from .db import init_engine, get_session_factory
    from .db.migrations import run_migrations
    init_engine()
    run_migrations()
    return get_session_factory()


def cmd_migrate(args: argparse.Namespace) -> None:
    """Import a Strava bulk export into the MERON database."""
    from .db.migrations import migration_002_backfill_bulk
    _db_init()
    report = migration_002_backfill_bulk(args.export_dir)
    print(f"Migration complete: {report}")


def cmd_sync(args: argparse.Namespace) -> None:
    """Pull new activities from Strava via the OAuth API."""
    factory = _db_init()
    from .services.sync import run_strava_sync
    with factory() as session:
        report = run_strava_sync(user_id=current_user_id(), session=session)
        session.commit()
    print(f"Sync report: {report}")


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest a Strava export directory into the existing MERON database."""
    factory = _db_init()
    from .services.ingestion.strava_csv import ingest_bulk
    with factory() as session:
        report = ingest_bulk(args.export_dir, user_id=current_user_id(), session=session)
        session.commit()
    print(f"Ingest report: {report}")


def cmd_backfill_streams(args: argparse.Namespace) -> None:
    """Fetch per-second streams from the Strava API for every API-synced
    activity whose ``streams_blob`` is still NULL.

    Limited by ``--limit`` (default 200) per run so we don't burn through the
    daily Strava quota in one shot. Re-runnable; idempotent.
    """
    import time
    from sqlalchemy import select
    from .db.models import Activity
    from .auth.strava_oauth import refresh_if_needed
    from .services.enrichment_service import invalidate_cache
    from .streams import fetch_streams_from_strava, serialize_streams

    factory = _db_init()
    user_id = current_user_id()
    limit = max(1, int(getattr(args, "limit", 200) or 200))
    sleep_s = float(getattr(args, "sleep", 1.0) or 1.0)

    with factory() as auth_session:
        try:
            token = refresh_if_needed(user_id=user_id, session=auth_session)
        except Exception as e:
            print(f"Token refresh failed: {e}")
            return
    from stravalib import Client
    client = Client(access_token=token)

    with factory() as session:
        rows = session.scalars(
            select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.source == "strava",
                Activity.deleted_at.is_(None),
                Activity.streams_blob.is_(None),
            )
            .order_by(Activity.start_time.desc())
            .limit(limit)
        ).all()
        print(f"Backfilling streams for {len(rows)} activities...")

        filled = skipped = errored = 0
        for i, row in enumerate(rows, 1):
            sid = row.source_id
            if not sid:
                skipped += 1
                continue
            try:
                streams = fetch_streams_from_strava(client, int(sid))
            except Exception as e:
                print(f"  ! {sid}: {e}")
                errored += 1
                time.sleep(sleep_s)
                continue
            if not streams:
                print(f"  - {sid} {row.name[:40] if row.name else ''} (no streams)")
                skipped += 1
                time.sleep(sleep_s)
                continue
            row.streams_blob = serialize_streams(streams)
            session.flush()
            filled += 1
            print(f"  + {sid} {row.name[:40] if row.name else ''}")
            if i % 20 == 0:
                session.commit()
            time.sleep(sleep_s)
        session.commit()
        if filled > 0:
            invalidate_cache(user_id)

    print(f"\nDone: filled {filled}, skipped {skipped}, errors {errored}")


def cmd_backfill_lifts(args: argparse.Namespace) -> None:
    """Walk the static lifting program forward from ``--anchor`` and
    write a description onto every bare Weight Training activity."""
    factory = _db_init()
    from .services.backfill_lifts import backfill_lift_descriptions
    from .services.enrichment_service import invalidate_cache
    with factory() as session:
        report = backfill_lift_descriptions(
            session,
            user_id=current_user_id(),
            anchor_date=args.anchor,
        )
    if report.get("matched", 0) > 0:
        invalidate_cache()
    print(f"Backfill report: {report}")


def _header(title: str) -> str:
    return f"\n{'=' * 60}\n  {title}\n{'=' * 60}"


def _subheader(title: str) -> str:
    return f"\n--- {title} ---"


def cmd_summary(df: pd.DataFrame, profile: dict, args: argparse.Namespace) -> None:
    """Print full summary report."""
    # Profile
    name = f"{profile.get('First Name', '')} {profile.get('Last Name', '')}".strip()
    location = f"{profile.get('City', '').strip()}, {profile.get('State', '').strip()}"
    if name:
        print(f"\n  Athlete: {name}")
    if location.strip(", "):
        print(f"  Location: {location}")

    # Overall
    s = metrics.overall_summary(df)
    print(_header("OVERALL SUMMARY"))
    print(f"  Activities:     {s['total_activities']}")
    print(f"  Date Range:     {s['date_range']}")
    print(f"  Active Days:    {s['active_days']} / {s['span_days']} days ({s['active_days']/max(s['span_days'],1)*100:.0f}%)")
    print(f"  Total Distance: {s['total_distance_mi']:.1f} mi")
    print(f"  Total Time:     {s['total_moving_time_hr']:.1f} hours")
    print(f"  Total Calories: {s['total_calories']:,.0f}")
    print(f"  Total Elevation:{s['total_elevation_ft']:,.0f} ft")

    # By type
    print(_header("BY ACTIVITY TYPE"))
    ts = metrics.type_summary(df)
    table = []
    for _, row in ts.iterrows():
        table.append([
            row["type"],
            int(row["count"]),
            f"{row['total_mi']:.1f}",
            f"{row['total_time_hr']:.1f}",
            f"{row['avg_mi']:.2f}",
            metrics.format_duration(row["avg_time_min"]),
            row["avg_pace"],
            row["best_pace"],
            f"{row['avg_hr']:.0f}" if pd.notna(row["avg_hr"]) else "--",
            f"{row['total_calories']:,.0f}",
        ])
    print(tabulate(table,
        headers=["Type", "#", "Total Mi", "Total Hr", "Avg Mi", "Avg Time", "Avg Pace", "Best Pace", "Avg HR", "Calories"],
        tablefmt="simple",
    ))

    # Running deep dive
    rm = metrics.running_metrics(df)
    if rm:
        print(_header("RUNNING METRICS"))
        print(f"  Total Runs:       {rm['total_runs']}")
        print(f"  Total Miles:      {rm['total_miles']:.1f}")
        print(f"  Avg Distance:     {rm['avg_distance_mi']:.2f} mi")
        print(f"  Avg Pace:         {rm['avg_pace']} /mi")
        print(f"  Best Pace:        {rm['best_pace']} /mi")
        print(f"  Avg Heart Rate:   {rm['avg_hr']:.0f} bpm")
        print(f"  Max Heart Rate:   {rm['max_hr_ever']:.0f} bpm")
        print(f"  Total Elevation:  {rm['total_elevation_ft']:,.0f} ft")
        print(f"  Max Run Streak:   {rm['max_run_streak_days']} days")
        print(f"\n  Longest Run:      {rm['longest_run_mi']:.2f} mi — {rm['longest_run_name']} ({rm['longest_run_date']:%b %d, %Y})")
        print(f"  Fastest Run:      {rm['fastest_run_pace']} /mi — {rm['fastest_run_name']} ({rm['fastest_run_date']:%b %d, %Y})")

    # Personal records
    prs = metrics.personal_records(df)
    if prs:
        print(_header("PERSONAL RECORDS"))
        for key, rec in prs.items():
            label = key.replace("_", " ").title()
            extra = f" [{rec['type']}]" if "type" in rec else ""
            print(f"  {label}: {rec['value']} — {rec['name']} ({rec['date']:%b %d, %Y}){extra}")

    # HR zones
    print(_header("HEART RATE ZONES (by avg HR per activity)"))
    hz = metrics.hr_zone_distribution(df)
    hz_table = []
    for _, row in hz.iterrows():
        hz_table.append([
            row["zone"], row["hr_range"], int(row["activities"]),
            f"{row['pct_activities']:.1f}%", f"{row['total_time_hr']:.1f}h",
        ])
    print(tabulate(hz_table, headers=["Zone", "BPM Range", "Activities", "% Activities", "Time"], tablefmt="simple"))

    # Day of week
    print(_header("DAY OF WEEK (Runs)"))
    dow = metrics.day_of_week_distribution(df, "Run")
    dow_table = []
    for day, row in dow.iterrows():
        if pd.notna(row["count"]):
            dow_table.append([
                day, int(row["count"]),
                f"{row['avg_distance_mi']:.2f} mi",
                row["avg_pace_fmt"],
            ])
    print(tabulate(dow_table, headers=["Day", "Runs", "Avg Distance", "Avg Pace"], tablefmt="simple"))


def cmd_monthly(df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Print monthly summary."""
    atype = args.type
    ms = metrics.monthly_summary(df, atype)
    title = f"MONTHLY SUMMARY" + (f" ({atype})" if atype else "")
    print(_header(title))
    table = []
    for month, row in ms.iterrows():
        table.append([
            str(month), int(row["activities"]),
            f"{row['distance_mi']:.1f}",
            f"{row['moving_time_hr']:.1f}",
            f"{row['calories']:,.0f}",
            f"{row['elevation_ft']:,.0f}",
            f"{row['avg_hr']:.0f}" if pd.notna(row["avg_hr"]) else "--",
            row["avg_pace_fmt"],
        ])
    print(tabulate(table,
        headers=["Month", "#", "Miles", "Hours", "Calories", "Elev ft", "Avg HR", "Avg Pace"],
        tablefmt="simple",
    ))


def cmd_weekly(df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Print weekly summary."""
    atype = args.type
    n = args.weeks
    ws = metrics.weekly_summary(df, atype)
    if n:
        ws = ws.tail(n)
    title = f"WEEKLY SUMMARY" + (f" ({atype})" if atype else "")
    if n:
        title += f" — last {n} weeks"
    print(_header(title))
    table = []
    for week, row in ws.iterrows():
        table.append([
            str(week), int(row["activities"]),
            f"{row['distance_mi']:.1f}",
            f"{row['moving_time_hr']:.1f}",
            f"{row['calories']:,.0f}",
            f"{row['avg_hr']:.0f}" if pd.notna(row["avg_hr"]) else "--",
            row["avg_pace_fmt"],
        ])
    print(tabulate(table,
        headers=["Week", "#", "Miles", "Hours", "Calories", "Avg HR", "Avg Pace"],
        tablefmt="simple",
    ))


def cmd_recent(df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Show recent activities."""
    n = args.count
    recent = metrics.recent_activities(df, n)
    print(_header(f"LAST {n} ACTIVITIES"))
    table = []
    for _, row in recent.iterrows():
        table.append([
            row["date_str"], row["type"], row["name"][:30],
            f"{row['distance_mi']:.2f}", row["time"], row["pace"],
            f"{row['avg_hr']:.0f}" if pd.notna(row["avg_hr"]) else "--",
            f"{row['calories']:.0f}" if pd.notna(row["calories"]) else "--",
        ])
    print(tabulate(table,
        headers=["Date", "Type", "Name", "Miles", "Time", "Pace", "HR", "Cal"],
        tablefmt="simple",
    ))


def cmd_export(df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Export enriched CSV."""
    enriched = enrich(df)

    if args.type:
        enriched = enriched[enriched["type"] == args.type]

    # Format pace column for readability
    enriched["pace_fmt"] = enriched["pace_min_per_mi"].apply(metrics.format_pace)
    enriched["time_fmt"] = enriched["moving_time_min"].apply(metrics.format_duration)

    export_cols = [
        "date", "day_of_week", "type", "name",
        # Run details
        "run_type", "distance_mi", "time_fmt", "pace_fmt",
        "elevation_gain_ft",
        # Kid / conditions
        "with_kid", "weather_temp_f", "weather_condition",
        # Heart rate
        "avg_hr", "max_hr", "hr_adjustment", "adjusted_hr",
        # Load / fatigue
        "calories", "training_stress", "acute_load_7d", "chronic_load_28d",
        "freshness", "fatigue_level",
        # Lifting
        "program_day", "bench_weight", "bench_volume",
        "squat_weight", "squat_volume",
        "deadlift_weight", "deadlift_volume",
        "ohp_weight", "ohp_volume",
        "pullup_sets", "pullup_reps",
        "hip_thrust_weight", "lift_exercises",
        # Misc
        "gear", "description",
    ]
    # Only include columns that exist
    export_cols = [c for c in export_cols if c in enriched.columns]

    enriched[export_cols].to_csv(args.output, index=False)
    print(f"Exported {len(enriched)} activities to {args.output}")

    # Print a quick summary of the enrichments
    runs = enriched[enriched["type"] == "Run"]
    kid_runs = runs[runs["with_kid"]]
    lifts = enriched[enriched["program_day"].notna()]
    print(f"\n  Runs: {len(runs)}  ({len(kid_runs)} with stroller/kids)")
    print(f"  Lifts mapped to program: {len(lifts)}")
    if not kid_runs.empty:
        print(f"  Avg HR adjustment (kid runs): -{kid_runs['hr_adjustment'].mean():.1f} bpm")
    hot = runs[runs["weather_temp_f"] > 60]
    if not hot.empty:
        print(f"  Avg temp adjustment (runs >60F): -{hot['hr_adjustment'].mean():.1f} bpm")
    fatigue_counts = enriched["fatigue_level"].value_counts()
    print(f"  Fatigue distribution: {dict(fatigue_counts)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strava export analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "export_dir",
        nargs="?",
        default=None,
        help="Path to Strava export directory (omit for DB-only commands: migrate, sync, ingest)",
    )

    sub = parser.add_subparsers(dest="command")

    # summary (default)
    sub.add_parser("summary", help="Full summary report (default)")

    # monthly
    p_monthly = sub.add_parser("monthly", help="Monthly summary")
    p_monthly.add_argument("--type", "-t", help="Filter by activity type (e.g. Run)")

    # weekly
    p_weekly = sub.add_parser("weekly", help="Weekly summary")
    p_weekly.add_argument("--type", "-t", help="Filter by activity type")
    p_weekly.add_argument("--weeks", "-w", type=int, help="Show last N weeks")

    # recent
    p_recent = sub.add_parser("recent", help="Recent activities")
    p_recent.add_argument("--count", "-n", type=int, default=15, help="Number of activities")

    # export
    p_export = sub.add_parser("export", help="Export enriched CSV with all metrics")
    p_export.add_argument(
        "--output", "-o", default="strava_enriched.csv",
        help="Output CSV path (default: strava_enriched.csv)",
    )
    p_export.add_argument("--type", "-t", help="Filter to activity type (e.g. Run)")

    # migrate — import a Strava export into the MERON DB
    p_migrate = sub.add_parser("migrate", help="Import Strava export into MERON DB")
    p_migrate.add_argument("--from", dest="export_dir", required=True,
                           help="Path to Strava export directory")

    # sync — pull from Strava API
    sub.add_parser("sync", help="Pull new activities from Strava via OAuth API")

    # ingest — incremental bulk ingest
    p_ingest = sub.add_parser("ingest", help="Incremental bulk ingest from an export dir")
    p_ingest.add_argument("export_dir", help="Path to Strava export directory")

    # backfill-lifts — write program-day descriptions onto bare lifts
    p_backfill = sub.add_parser(
        "backfill-lifts",
        help="Write program-day descriptions onto bare Weight Training activities",
    )
    p_backfill.add_argument(
        "--anchor", default=None,
        help="ISO date (YYYY-MM-DD) of the program's first lift. "
             "Defaults to lifting_program.PROGRAM_ANCHOR_DATE.",
    )

    # backfill-streams — pull per-second Strava streams onto rows missing them
    p_streams = sub.add_parser(
        "backfill-streams",
        help="Fetch per-second streams from Strava for API-synced activities lacking them",
    )
    p_streams.add_argument(
        "--limit", type=int, default=200,
        help="Max activities to process this run (default 200).",
    )
    p_streams.add_argument(
        "--sleep", type=float, default=1.0,
        help="Seconds between API calls (default 1.0).",
    )

    args = parser.parse_args()

    # DB-only commands short-circuit before needing an export_dir
    if args.command == "migrate":
        cmd_migrate(args)
        return
    if args.command == "sync":
        cmd_sync(args)
        return
    if args.command == "ingest":
        cmd_ingest(args)
        return
    if args.command == "backfill-lifts":
        cmd_backfill_lifts(args)
        return
    if args.command == "backfill-streams":
        cmd_backfill_streams(args)
        return

    # Data commands need a source. Prefer `export_dir` if provided, else
    # fall back to the DB (so users can run `strava summary` after `migrate`).
    if args.export_dir:
        df = load_activities(args.export_dir)
        profile = load_profile(args.export_dir)
    else:
        # DB-backed path
        from .web import data
        data.init(None)
        df = data.get_df()
        profile = data.get_profile()

    if args.command is None or args.command == "summary":
        cmd_summary(df, profile, args)
    elif args.command == "monthly":
        cmd_monthly(df, args)
    elif args.command == "weekly":
        cmd_weekly(df, args)
    elif args.command == "recent":
        cmd_recent(df, args)
    elif args.command == "export":
        cmd_export(df, args)


if __name__ == "__main__":
    main()
