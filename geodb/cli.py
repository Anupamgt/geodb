"""
CLI entrypoint for geodb.
"""
import json
import os
import sys
import glob
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

import click
from tabulate import tabulate

from geodb.config import DATA_DIR, SUPPORTED_EXTENSIONS, DEFAULT_WORKERS, STORE_BLOBS
from geodb.db.connection import ShardManager
from geodb.db.reader import ShardReader, CatalogReader
from geodb.db.writer import ingest_file
from geodb.ingest.router import route


# ── Helpers ──────────────────────────────────────────────────────────────────

def _collect_files(path):
    """Recursively find all supported files."""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(glob.glob(os.path.join(path, "**", f"*{ext}"), recursive=True))
        # Also uppercase
        files.extend(glob.glob(os.path.join(path, "**", f"*{ext.upper()}"), recursive=True))
    return sorted(set(files))


def _ingest_single(filepath, use_spatialite=True):
    """Ingest a single file. Used by both serial and parallel modes."""
    try:
        data = route(filepath)
    except Exception as e:
        return filepath, f"error:parse:{e}"

    mgr = ShardManager(use_spatialite=use_spatialite)
    try:
        shard = mgr.get_shard(data["year"])
        catalog = mgr.get_catalog()
        result = ingest_file(data, shard, catalog, use_spatialite=use_spatialite)
        return filepath, result
    except Exception as e:
        return filepath, f"error:write:{e}"
    finally:
        mgr.close()


# ── CLI ──────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """geodb - Geospatial file storage in SQLite."""
    os.makedirs(DATA_DIR, exist_ok=True)


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--workers", "-w", default=1, help="Parallel workers (use 1 for serial)")
@click.option("--no-spatialite", is_flag=True, help="Disable SpatiaLite")
def ingest(path, workers, no_spatialite):
    """Ingest KML/TIF files from PATH into the database."""
    use_spat = not no_spatialite
    files = _collect_files(path)
    total = len(files)
    click.echo(f"Found {total} files to ingest.")

    if total == 0:
        return

    counts = Counter()
    errors = []
    start = time.time()

    if workers <= 1:
        mgr = ShardManager(use_spatialite=use_spat)
        catalog = mgr.get_catalog()
        for i, fp in enumerate(files, 1):
            try:
                data = route(fp)
                shard = mgr.get_shard(data["year"])
                result = ingest_file(data, shard, catalog, use_spatialite=use_spat)
            except Exception as e:
                result = f"error:{e}"

            counts[result.split(":")[0]] += 1
            if result.startswith("error"):
                errors.append((fp, result))

            if i % 50 == 0 or i == total:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                click.echo(f"  [{i}/{total}] {rate:.1f} files/sec")

        mgr.close()
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_ingest_single, fp, use_spat): fp
                for fp in files
            }
            done = 0
            for future in as_completed(futures):
                done += 1
                fp, result = future.result()
                counts[result.split(":")[0]] += 1
                if result.startswith("error"):
                    errors.append((fp, result))
                if done % 50 == 0 or done == total:
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed > 0 else 0
                    click.echo(f"  [{done}/{total}] {rate:.1f} files/sec")

    elapsed = time.time() - start
    click.echo(f"\nDone in {elapsed:.1f}s")
    click.echo(f"  Inserted: {counts.get('inserted', 0)}")
    click.echo(f"  Skipped:  {counts.get('skipped', 0)}")
    click.echo(f"  Errors:   {counts.get('error', 0)}")

    if errors:
        click.echo("\nErrors:")
        for fp, err in errors[:20]:
            click.echo(f"  {fp}: {err}")
        if len(errors) > 20:
            click.echo(f"  ... and {len(errors) - 20} more")


@cli.command()
@click.option("--bbox", type=str, help="minx,miny,maxx,maxy")
@click.option("--text", "-t", type=str, help="Full-text search query")
@click.option("--type", "file_type", type=click.Choice(["kml", "tif"]))
@click.option("--year", type=int)
@click.option("--tags", type=str, help="Comma-separated tags (AND)")
@click.option("--bands", type=int)
@click.option("--min-res", type=float)
@click.option("--max-res", type=float)
@click.option("--crs", type=int)
@click.option("--geometry-type", type=str)
@click.option("--sensor", type=str)
@click.option("--cloud-cover-max", type=float)
@click.option("--temporal-start", type=str)
@click.option("--temporal-end", type=str)
@click.option("--limit", "-l", type=int, default=50)
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.option("--no-spatialite", is_flag=True)
def search(bbox, text, file_type, year, tags, bands, min_res, max_res,
           crs, geometry_type, sensor, cloud_cover_max,
           temporal_start, temporal_end, limit, json_output, no_spatialite):
    """Search files across shards."""
    use_spat = not no_spatialite
    mgr = ShardManager(use_spatialite=use_spat)
    cat_reader = CatalogReader(mgr.get_catalog())

    # Parse bbox
    bbox_tuple = None
    if bbox:
        bbox_tuple = tuple(float(x) for x in bbox.split(","))

    # Parse tags
    tag_list = [t.strip().lower() for t in tags.split(",")] if tags else None

    # Determine which shards to query
    years = cat_reader.find_shards(
        bbox=bbox_tuple,
        temporal_start=temporal_start,
        temporal_end=temporal_end,
        text=text,
        year=year,
    )

    if not years:
        click.echo("No matching shards found.")
        mgr.close()
        return

    # Query each shard
    all_results = []
    for y in years:
        shard = mgr.get_shard(y)
        reader = ShardReader(shard, use_spatialite=use_spat)

        # Build filter kwargs
        fkw = {}
        if file_type: fkw["file_type"] = file_type
        if crs: fkw["crs"] = crs
        if min_res is not None: fkw["min_res"] = min_res
        if max_res is not None: fkw["max_res"] = max_res
        if bands: fkw["bands"] = bands
        if tag_list: fkw["tags"] = tag_list
        if sensor: fkw["sensor"] = sensor
        if cloud_cover_max is not None: fkw["cloud_cover_max"] = cloud_cover_max
        if geometry_type: fkw["geometry_type"] = geometry_type
        if temporal_start: fkw["temporal_start"] = temporal_start
        if temporal_end: fkw["temporal_end"] = temporal_end

        results = reader.search_combined(
            bbox=bbox_tuple, text=text, **fkw
        )
        for r in results:
            r["year"] = y
        all_results.extend(results)

        if len(all_results) >= limit:
            break

    all_results = all_results[:limit]
    mgr.close()

    if not all_results:
        click.echo("No results found.")
        return

    if json_output:
        # Remove non-serializable fields
        for r in all_results:
            r.pop("blob", None)
            r.pop("geometry", None)
        click.echo(json.dumps(all_results, indent=2, default=str))
    else:
        headers = ["year", "id", "filename", "file_type", "bbox_minx",
                    "bbox_miny", "bbox_maxx", "bbox_maxy"]
        rows = [[r.get(h, "") for h in headers] for r in all_results]
        click.echo(tabulate(rows, headers=headers, tablefmt="simple"))
        click.echo(f"\n{len(all_results)} results")


@cli.command()
@click.argument("year", type=int)
@click.argument("file_id", type=int)
@click.option("-o", "--output", type=click.Path(), default=".")
@click.option("--no-spatialite", is_flag=True)
def export(year, file_id, output, no_spatialite):
    """Export a file from the database to disk."""
    use_spat = not no_spatialite
    mgr = ShardManager(use_spatialite=use_spat)
    shard = mgr.get_shard(year)
    reader = ShardReader(shard, use_spatialite=use_spat)

    meta = reader.get_metadata(file_id)
    if not meta:
        click.echo(f"File {file_id} not found in year {year}.")
        mgr.close()
        return

    data = reader.get_blob(file_id)
    if not data:
        click.echo("No blob data available for this file.")
        mgr.close()
        return

    os.makedirs(output, exist_ok=True)
    outpath = os.path.join(output, meta["filename"])
    with open(outpath, "wb") as f:
        f.write(data)

    click.echo(f"Exported to {outpath} ({len(data)} bytes)")
    mgr.close()


@cli.command()
@click.option("--no-spatialite", is_flag=True)
def stats(no_spatialite):
    """Show database statistics."""
    use_spat = not no_spatialite
    mgr = ShardManager(use_spatialite=use_spat)
    cat_reader = CatalogReader(mgr.get_catalog())

    shard_stats = cat_reader.shard_stats()
    if not shard_stats:
        click.echo("No shards found. Run 'geodb ingest' first.")
        mgr.close()
        return

    headers = ["Year", "Files", "Size (MB)", "Created"]
    rows = [
        [s["year"], s["file_count"],
         f"{s['size_bytes'] / 1e6:.1f}",
         s["created_at"]]
        for s in shard_stats
    ]
    total_files = sum(s["file_count"] for s in shard_stats)
    total_size = sum(s["size_bytes"] for s in shard_stats)

    click.echo(tabulate(rows, headers=headers, tablefmt="simple"))
    click.echo(f"\nTotal: {total_files} files, {total_size / 1e6:.1f} MB "
               f"across {len(shard_stats)} shards")
    mgr.close()


@cli.command("list-tags")
@click.option("--no-spatialite", is_flag=True)
def list_tags(no_spatialite):
    """List all unique tags across shards."""
    use_spat = not no_spatialite
    mgr = ShardManager(use_spatialite=use_spat)
    cat_reader = CatalogReader(mgr.get_catalog())
    tags = cat_reader.list_all_tags()
    for t in tags:
        click.echo(t)
    click.echo(f"\n{len(tags)} unique tags")
    mgr.close()


if __name__ == "__main__":
    cli()
