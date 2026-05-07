import httpx
import os
import time

url = "https://metaporn.n8nmikael.com.br/uploads/proxy"
payload_size = 5 * 1024 * 1024 # 5MB
print(f"Uploading {payload_size} bytes to {url}...")

# Create a temporary file to upload
with open("test_upload.tmp", "wb") as f:
    f.write(b'x' * payload_size)

try:
    with open("test_upload.tmp", "rb") as f:
        files = {'file': ('test.mp4', f, 'video/mp4')}
        start_time = time.time()
        r = httpx.post(url, files=files, timeout=600.0)
        end_time = time.time()
        print(f"Status Code: {r.status_code}")
        print(f"Response: {r.text}")
        print(f"Time Taken: {end_time - start_time:.2f} seconds")
except Exception as e:
    print(f"Exception: {e}")
finally:
    if os.path.exists("test_upload.tmp"):
        os.remove("test_upload.tmp")
