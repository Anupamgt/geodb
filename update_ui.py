import os
import re

html_path = 'geodb/web/static/index.html'
with open(html_path, 'r') as f:
    html = f.read()

# CSS Variables for VS Code Dark Theme
html = html.replace('--bg: #0f1117;', '--bg: #1e1e1e;')
html = html.replace('--surface: #1a1d27;', '--surface: #252526;')
html = html.replace('--surface2: #22263a;', '--surface2: #2d2d30;')
html = html.replace('--border: #2e3250;', '--border: #3e3e42;')
html = html.replace('--accent: #4f8ef7;', '--accent: #007acc;') # VS Code blue
html = html.replace('--accent2: #38bdf8;', '--accent2: #4fc1ff;')
html = html.replace('--radius: 10px;', '--radius: 0px;')
html = html.replace('border-radius: 8px;', 'border-radius: 0px;')
html = html.replace('border-radius: 6px;', 'border-radius: 0px;')
html = html.replace('border-radius: 20px;', 'border-radius: 0px;')

# Emoticons in HTML
emojis = ['🌍', '🔍', '➕', '🤖', '📂', '⚡', '🗺️', '✅', '❌', '⚠️', '⚙️', '📁', '⬆️', '▶', '⏎', '📋', '📤', '🔧', '🎨', '💾', '📊', '🚀']
for e in emojis:
    html = html.replace(e, '')

html = html.replace('  GeoFlow', ' GeoFlow')

# Add token indicator in the header next to logo
logo_end = html.find('</div>', html.find('<div class="logo">')) + 6
indicator_html = '\n  <div id="tokenBadge" style="margin-left:20px; font-size:12px; color:var(--muted); border-left:1px solid var(--border); padding-left:15px; display:flex; align-items:center;">API: &nbsp;<span id="tokenCount" style="color:var(--text);">0</span>/100 Tokens Exhausted</div>'
if 'id="tokenBadge"' not in html:
    html = html[:logo_end] + indicator_html + html[logo_end:]

# Update JS to fetch token usage
js_addition = """
async function updateTokens() {
  try {
    const r = await fetch('/api/status');
    if (r.ok) {
      const data = await r.json();
      document.getElementById('tokenCount').innerText = data.tokens_used;
    }
  } catch(e) {}
}
setInterval(updateTokens, 2000);
"""
if 'updateTokens()' not in html:
    html = html.replace('loadAgents();', 'loadAgents();\n  updateTokens();')
    idx = html.rfind('</script>')
    if idx != -1:
        html = html[:idx] + js_addition + '\n' + html[idx:]

with open(html_path, 'w') as f:
    f.write(html)

for llm_path in ['geodb/agent_factory/llm_client.py', 'geodb/transform/llm_client.py']:
    if not os.path.exists(llm_path): continue
    with open(llm_path, 'r') as f:
        code = f.read()

    if 'global_tokens_used =' not in code:
        code = code.replace('class LLMClient:', 'class LLMClient:\n    global_tokens_used = 0\n')
        code = re.sub(
            r'return r\.json\(\)\["choices"\]\[0\]\["message"\]\["content"\]\.strip\(\)',
            r'resp_json = r.json()\n                usage = resp_json.get("usage", {})\n                type(self).global_tokens_used += usage.get("total_tokens", 0)\n                return resp_json["choices"][0]["message"]["content"].strip()',
            code
        )
        code = re.sub(
            r'blocks = r\.json\(\)\.get\("content", \[\]\)',
            r'resp_json = r.json()\n            usage = resp_json.get("usage", {})\n            type(self).global_tokens_used += (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))\n            blocks = resp_json.get("content", [])',
            code
        )
        
    with open(llm_path, 'w') as f:
        f.write(code)

app_path = 'geodb/web/app.py'
with open(app_path, 'r') as f:
    app_code = f.read()

status_endpoint = """
@app.get("/api/status")
async def api_status():
    from geodb.agent_factory.llm_client import LLMClient
    return {"tokens_used": LLMClient.global_tokens_used, "tokens_limit": 100}
"""
if '/api/status' not in app_code:
    app_code = app_code.replace('# ── Agents', status_endpoint + '\n# ── Agents')
    with open(app_path, 'w') as f:
        f.write(app_code)

python_files = [
    'geodb/web/runner.py',
    'geodb/transform/pipeline/orchestrator.py',
    'geodb/web/__main__.py'
]

for path in python_files:
    if not os.path.exists(path): continue
    with open(path, 'r') as f:
        content = f.read()
    
    for e in emojis:
        content = content.replace(e + ' ', '')
        content = content.replace(e, '')
        
    with open(path, 'w') as f:
        f.write(content)

print("Done")
