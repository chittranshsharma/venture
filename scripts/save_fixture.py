import sys
from playwright.sync_api import sync_playwright

if len(sys.argv) < 3:
    print("Usage: python scripts/save_fixture.py <url> <output_path>")
    sys.exit(1)

import re

url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(url, wait_until="networkidle")
    html = pg.content()
    b.close()

# Strip scripts to sanitize while keeping form inputs, labels, and structural DOM
clean_html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
with open(out, "w", encoding="utf-8") as f:
    f.write(clean_html)

print(f"Sanitized real DOM fixture saved to {out} ({len(clean_html)} chars)")

