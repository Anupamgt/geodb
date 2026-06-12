"""
Map Renderer — takes step output files, extracts spatial data,
renders on the fixed dark India map template, opens in browser.
"""
import os
import webbrowser

from geodb.agent_factory.maps.data_extractor import extract_map_data
from geodb.agent_factory.maps.template import build_map_html
from geodb.agent_factory.config import OUTPUT_DIR


def render_step_map(step_name: str, output_paths: dict,
                    output_dir: str = None) -> str:
    """
    Render a map for a step's output and return the HTML file path.

    Args:
        step_name: name of the step (used in title and filename)
        output_paths: {filename: full_path} of step outputs
        output_dir: where to save the HTML (default: OUTPUT_DIR/maps/)

    Returns: path to the saved HTML file, or "" if no spatial data
    """
    # Extract plottable data
    map_data = extract_map_data(output_paths)

    if not map_data["has_data"]:
        return ""

    # Build HTML
    html = build_map_html(
        geojson_features=map_data["features"],
        bounds=map_data["bounds"],
        title=f"Step: {step_name}",
        summary=map_data["summary"],
    )

    # Save
    save_dir = os.path.join(output_dir or OUTPUT_DIR, "maps")
    os.makedirs(save_dir, exist_ok=True)

    safe_name = step_name.replace(" ", "_").replace("/", "_")
    filepath = os.path.join(save_dir, f"map_{safe_name}.html")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    return filepath


def open_map(filepath: str):
    """Open the map HTML in the default browser."""
    if filepath and os.path.isfile(filepath):
        try:
            url = f"file://{os.path.abspath(filepath)}"
            webbrowser.open(url)
            return True
        except Exception:
            pass
    return False


def render_and_open(step_name: str, output_paths: dict,
                    output_dir: str = None) -> str:
    """Render map and immediately open in browser. Returns filepath."""
    filepath = render_step_map(step_name, output_paths, output_dir)
    if filepath:
        open_map(filepath)
    return filepath
