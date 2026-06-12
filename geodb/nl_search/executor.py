"""
Execute verified SQL across year-sharded SQLite databases.
Read-only: PRAGMA query_only = ON on every connection.
"""
import os
import sqlite3
from geodb.nl_search.config import SAFE_ROW_LIMIT


class Executor:

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.shards = self._discover()

    def _discover(self) -> dict:
        """Find all year-shard DBs in data_dir."""
        shards = {}
        if not os.path.isdir(self.data_dir):
            return shards
        for f in sorted(os.listdir(self.data_dir)):
            if f.endswith(".db") and f != "catalog.db":
                try:
                    shards[int(f[:-3])] = os.path.join(self.data_dir, f)
                except ValueError:
                    pass
        return shards

    def list_years(self) -> list:
        return sorted(self.shards.keys())

    def run(self, sql: str, years: list = None) -> dict:
        """
        Run sql on requested shards, merge results.
        Returns { columns, rows, count, shards, errors }.
        """
        targets = years or self.list_years()
        rows_all = []
        columns = None
        errors = []

        for year in targets:
            path = self.shards.get(year)
            if not path:
                continue
            try:
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")

                # Try loading SpatiaLite for spatial functions
                try:
                    conn.enable_load_extension(True)
                    conn.load_extension("mod_spatialite")
                except Exception:
                    pass

                cursor = conn.execute(sql)
                rows = cursor.fetchall()

                if rows and columns is None:
                    columns = list(rows[0].keys())

                for r in rows:
                    d = dict(r)
                    d["_year"] = year
                    rows_all.append(d)

                conn.close()
            except sqlite3.Error as e:
                errors.append({"year": year, "error": str(e)})
            except Exception as e:
                errors.append({"year": year, "error": str(e)})

        rows_all = rows_all[:SAFE_ROW_LIMIT]

        return {
            "columns": (columns or []) + ["_year"],
            "rows": rows_all,
            "count": len(rows_all),
            "shards": len(targets),
            "errors": errors,
        }
