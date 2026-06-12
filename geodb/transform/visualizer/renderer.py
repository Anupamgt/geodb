"""
Renderer — saves visualization HTML to files and optionally opens in browser.
Also generates the combined pipeline report.
"""
import os
import webbrowser
from geodb.transform.config import OUTPUT_DIR, VIZ_CDN


def save_step_viz(step_id: int, step_name: str, html: str, output_dir: str = None) -> str:
    """Save step visualization HTML and return the file path."""
    out_dir = output_dir or OUTPUT_DIR
    viz_dir = os.path.join(out_dir, "viz")
    os.makedirs(viz_dir, exist_ok=True)

    filename = f"step_{step_id}_{step_name}.html"
    filepath = os.path.join(viz_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath


def open_in_browser(filepath: str):
    """Open an HTML file in the default browser."""
    try:
        url = f"file://{os.path.abspath(filepath)}"
        webbrowser.open(url)
    except Exception:
        pass  # Silently fail if no browser


def generate_pipeline_report(task: str, steps: list, output_dir: str = None) -> str:
    """
    Generate a combined HTML report with a slider to navigate between steps.

    Args:
        task: original task description
        steps: list of Step objects (must have viz_html_path populated)
        output_dir: where to save the report

    Returns: path to pipeline_report.html
    """
    out_dir = output_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    # Collect step viz HTML content (embed inline via iframes or divs)
    step_data = []
    for step in steps:
        entry = {
            "id": step.id,
            "name": step.name,
            "description": step.description,
            "status": step.status,
            "exec_time": step.exec_time,
            "viz_summary": step.viz_summary or "",
            "viz_path": step.viz_html_path or "",
        }
        step_data.append(entry)

    html = _build_report_html(task, step_data)
    report_path = os.path.join(out_dir, "pipeline_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return report_path


def _build_report_html(task: str, step_data: list) -> str:
    steps_json = []
    for s in step_data:
        steps_json.append({
            "id": s["id"],
            "name": s["name"],
            "description": s["description"],
            "status": s["status"],
            "time": f"{s['exec_time']:.1f}s",
            "summary": s["viz_summary"],
            "viz_url": s["viz_path"],
        })

    import json
    steps_js = json.dumps(steps_json, default=str)

    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Pipeline Report</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0f0f1a; color:#e0e0e0; font-family: 'Segoe UI', sans-serif; }}
.header {{ background:#16213e; padding:20px 32px; border-bottom:2px solid #4fc3f7; }}
.header h1 {{ font-size:22px; color:#4fc3f7; }}
.header p {{ color:#aaa; margin-top:4px; }}
.step-nav {{ display:flex; gap:8px; padding:16px 32px; background:#1a1a2e; overflow-x:auto; }}
.step-btn {{
    padding:10px 20px; border:2px solid #333; border-radius:8px;
    background:#16213e; color:#ccc; cursor:pointer; white-space:nowrap;
    transition:all 0.2s;
}}
.step-btn.active {{ border-color:#4fc3f7; color:#4fc3f7; background:#1a2744; }}
.step-btn.completed {{ border-color:#4caf50; }}
.step-btn.failed {{ border-color:#f44336; }}
.step-detail {{ padding:24px 32px; }}
.step-info {{ margin-bottom:16px; }}
.step-info h2 {{ color:#4fc3f7; margin-bottom:8px; }}
.step-info .meta {{ color:#888; font-size:14px; }}
.step-info .summary {{ margin-top:12px; white-space:pre-wrap; font-family:monospace;
    background:#16213e; padding:12px; border-radius:6px; font-size:13px; }}
.viz-frame {{ width:100%; height:70vh; border:1px solid #333; border-radius:8px;
    background:#1a1a2e; }}
.flow {{ display:flex; align-items:center; gap:4px; padding:8px 32px; flex-wrap:wrap; }}
.flow-step {{ padding:6px 14px; border-radius:4px; font-size:13px; }}
.flow-step.completed {{ background:#1b5e20; color:#a5d6a7; }}
.flow-step.failed {{ background:#b71c1c; color:#ef9a9a; }}
.flow-step.pending {{ background:#333; color:#888; }}
.flow-arrow {{ color:#555; }}
</style>
</head>
<body>

<div class="header">
    <h1>Pipeline Report</h1>
    <p>{task}</p>
</div>

<div class="flow" id="flow"></div>
<div class="step-nav" id="stepNav"></div>
<div class="step-detail" id="stepDetail"></div>

<script>
const steps = {steps_js};
let currentStep = 0;

function renderFlow() {{
    const el = document.getElementById('flow');
    el.innerHTML = steps.map((s, i) =>
        `<span class="flow-step ${{s.status}}">${{s.id}}. ${{s.name}} (${{s.time}})</span>` +
        (i < steps.length-1 ? '<span class="flow-arrow">→</span>' : '')
    ).join('');
}}

function renderNav() {{
    const el = document.getElementById('stepNav');
    el.innerHTML = steps.map((s, i) =>
        `<button class="step-btn ${{s.status}} ${{i===currentStep?'active':''}}"
                 onclick="showStep(${{i}})">
            Step ${{s.id}}: ${{s.name}}
        </button>`
    ).join('');
}}

function showStep(idx) {{
    currentStep = idx;
    renderNav();
    const s = steps[idx];
    const el = document.getElementById('stepDetail');
    let viz = '';
    if (s.viz_url) {{
        viz = `<iframe class="viz-frame" src="file://${{s.viz_url}}"></iframe>`;
    }}
    el.innerHTML = `
        <div class="step-info">
            <h2>Step ${{s.id}}: ${{s.name}}</h2>
            <div class="meta">${{s.description}} — ${{s.status}} in ${{s.time}}</div>
            <div class="summary">${{s.summary}}</div>
        </div>
        ${{viz}}
    `;
}}

renderFlow();
renderNav();
if (steps.length) showStep(0);
</script>
</body>
</html>"""
