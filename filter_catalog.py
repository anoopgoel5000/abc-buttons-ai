import sys, json

catalog_path = r"C:\Users\shaur\.gemini\antigravity\scratch\abc-buttons-ai\catalog.py"
sys.path.append(r"C:\Users\shaur\.gemini\antigravity\scratch\abc-buttons-ai")
from catalog import SAMPLE_CATALOG

real_skus = [
    'ABC-136', 'ABC-137', 'ABC-138', 'ABC-139', 'ABC-140', 'ABC-141', 'ABC-142', 'ABC-143',
    'ABC-144', 'ABC-145', 'ABC-146', 'ABC-147', 'ABC-148', 'ABC-149', 'ABC-150', 'ABC-151',
    'ABC-152', 'ABC-153', 'ABC-POLY-18L-08', 'ABC-POLY-18L-10'
]

def sort_key(item):
    sku = item['sku']
    if sku.startswith('ABC-') and len(sku) >= 7 and sku[4:7].isdigit():
        return (0, int(sku[4:7]))
    return (1, sku)

filtered = [item for item in SAMPLE_CATALOG if item['sku'] in real_skus]
filtered.sort(key=sort_key)

print(f"Total kept: {len(filtered)}")
for x in filtered:
    print(x['sku'], "|", x['name'])

header = '"""\nABC Buttons - Product Catalog Master & Pricing Matrix\nFeaturing 100% Genuine Real Factory Photography Products.\nAll quantities and rates strictly in GROSS (1 Gross = 144 Pieces).\n"""\n\nSAMPLE_CATALOG = '
footer = '''\n\ndef search_catalog_by_text(query: str):
    query = query.lower()
    results = []
    for item in SAMPLE_CATALOG:
        text = f"{item['sku']} {item['name']} {item['category']} {item['material']} {item['finish']} {item['recommended_garment']}".lower()
        if any(word in text for word in query.split()):
            results.append(item)
    return results or SAMPLE_CATALOG[:5]
'''

full_code = header + json.dumps(filtered, indent=4) + footer
with open(catalog_path, "w", encoding="utf-8") as f:
    f.write(full_code)

print("SUCCESS: Updated catalog.py with only 20 real photo items!")
