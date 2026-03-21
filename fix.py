with open('app.py', 'r') as f:
    content = f.read()

# Find the buttons section and remove all SVG from it
# Replace the entire buttons div with a simple version
old = '''  <div style="display:flex;flex-direction:column;gap:10px;width:100%;max-width:360px;z-index:1">

    <div style="height:10px"></div>

    <div style="display:flex;align-items:center;gap:10px;margin:4px 0">
      <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
      <div style="font-size:10px;color:rgba(255,255,255,0.18)">also connect after login</div>
      <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
    </div>'''

new = '''  <div style="display:flex;flex-direction:column;gap:10px;width:100%;max-width:360px;z-index:1">

    <div style="display:flex;align-items:center;gap:10px;margin:4px 0">
      <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
      <div style="font-size:10px;color:rgba(255,255,255,0.18)">also connect after login</div>
      <div style="flex:1;height:1px;background:rgba(255,255,255,0.06)"></div>
    </div>'''

if old in content:
    content = content.replace(old, new)
    print("Removed height:10px spacer")

# Now remove ALL SVG tags from the buttons section to fix rendering
import re

# Replace SVG icons in buttons with emoji
svg_replacements = [
    # Telegram SVG
    (r'<svg width="20" height="20" viewBox="0 0 24 24" fill="#229ED9">.*?</svg>', '✈️', re.DOTALL),
    # WhatsApp SVG  
    (r'<svg width="20" height="20" viewBox="0 0 24 24" fill="#25D366">.*?</svg>', '💬', re.DOTALL),
    # LinkedIn SVG
    (r'<svg width="20" height="20" viewBox="0 0 24 24" fill="#0A66C2">.*?</svg>', '💼', re.DOTALL),
    # Twitter SVG
    (r'<svg width="20" height="20" viewBox="0 0 24 24" fill="rgba\(255,255,255,0\.5\)">.*?</svg>', '🐦', re.DOTALL),
]

for pattern, replacement, flags in svg_replacements:
    content = re.sub(pattern, replacement, content, flags=flags)
    print(f"Replaced SVG with {replacement}")

with open('app.py', 'w') as f:
    f.write(content)
print("Done!")
