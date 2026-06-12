"""
Routes files to the correct parser and prepares unified ingest data.
"""
import hashlib
import os

from geodb.config import STORE_BLOBS, SUPPORTED_EXTENSIONS, MAX_BLOB_BYTES
from geodb.ingest import kml_parser, tif_parser


def compute_hash(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(1 << 20)  # 1MB
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def route(filepath: str) -> dict:
    """
    Parse a file and return a unified dict ready for the writer.

    Returns dict with keys:
        filepath, filename, file_type, hash_sha256, size_bytes,
        blob (bytes or None), year, and all metadata fields.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported extension: {ext}")

    if ext in (".kml", ".kmz"):
        meta = kml_parser.parse(filepath)
    elif ext in (".tif", ".tiff"):
        meta = tif_parser.parse(filepath)
    else:
        raise ValueError(f"No parser for {ext}")

    file_hash = compute_hash(filepath)
    size_bytes = os.path.getsize(filepath)

    blob = None
    if STORE_BLOBS and size_bytes <= MAX_BLOB_BYTES:
        with open(filepath, "rb") as f:
            blob = f.read()

    meta["filepath"] = filepath
    meta["filename"] = os.path.basename(filepath)
    meta["hash_sha256"] = file_hash
    meta["size_bytes"] = size_bytes
    meta["blob"] = blob

    return meta
