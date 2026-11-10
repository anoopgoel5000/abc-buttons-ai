import urllib.request
import re
import os

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
urls = [
    'https://www.indiamart.com/proddetail/china-river-shell-dw-buttons-24422204688.html',
    'https://www.indiamart.com/proddetail/river-shell-buttons-24422241512.html',
    'https://www.indiamart.com/proddetail/random-shell-buttons-24422262791.html',
    'https://www.indiamart.com/proddetail/mop-button-21876805097.html',
    'https://www.indiamart.com/proddetail/mother-of-pearl-shell-buttons-22879555512.html'
]

found_imgs = []
for u in urls:
    try:
        req = urllib.request.Request(u, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            matches = re.findall(r'https://[^\s"\'<>]+?\.imimg\.com/[^\s"\'<>]+?\.(?:jpg|jpeg|png)', html)
            for m in matches:
                if '500x500' in m or '1000x1000' in m or '250x250' in m:
                    found_imgs.append(m)
    except Exception as e:
        print(f"Error fetching {u}: {e}")

unique_imgs = list(set(found_imgs))
print(f"Found {len(unique_imgs)} high-res product images:")
for idx, img_url in enumerate(unique_imgs[:15]):
    print(f"[{idx}] {img_url}")

# Download them into catalog_images
dest_dir = r"C:\Users\shaur\.gemini\antigravity\scratch\abc-buttons-ai\catalog_images"
test_dir = r"C:\Users\shaur\.gemini\antigravity\scratch\abc-buttons-ai\test_inquiries"

downloaded = []
for idx, img_url in enumerate(unique_imgs[:12]):
    fname = f"abc_shell_web_{idx+1}.jpg"
    out_path = os.path.join(dest_dir, fname)
    try:
        req = urllib.request.Request(img_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp, open(out_path, 'wb') as f:
            f.write(resp.read())
        downloaded.append(fname)
        # Also copy to test_inquiries
        with open(out_path, 'rb') as src, open(os.path.join(test_dir, fname), 'wb') as dst:
            dst.write(src.read())
    except Exception as e:
        print(f"Failed to download {img_url}: {e}")

print(f"Successfully downloaded {len(downloaded)} real product images!")
