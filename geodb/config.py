import os

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CATALOG_DB_PATH = os.path.join(DATA_DIR, "catalog.db")

# Storage
STORE_BLOBS = True        # False = store file paths only
MAX_BLOB_BYTES = 500 * 1024 * 1024  # files larger than 500 MB → store path only
BATCH_SIZE = 500
DEFAULT_WORKERS = 4

# SQLite PRAGMAs applied to every connection
SHARD_PRAGMAS = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "cache_size": -512000,
    "temp_store": "MEMORY",
    "mmap_size": 268435456,
}

PAGE_SIZE = 65536
SPATIALITE_EXT = "mod_spatialite"
DEFAULT_SRID = 4326
SUPPORTED_EXTENSIONS = {".kml", ".kmz", ".tif", ".tiff"}


def shard_db_path(year: int) -> str:
    return os.path.join(DATA_DIR, f"{year}.db")
