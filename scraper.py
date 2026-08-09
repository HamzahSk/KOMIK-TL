import json
import subprocess

def run_node_scraper(action, url):
    """Memanggil script Node.js dan mengambil output JSON-nya"""
    try:
        # PENTING: Ganti nama file menjadi node_scraper.mjs
        result = subprocess.run(
            ['node', 'node_scraper.mjs', action, url],
            capture_output=True, text=True, check=True, encoding='utf-8'
        )
        
        lines = result.stdout.strip().split('\n')
        if not lines or lines[-1] == "null":
            return None
            
        return json.loads(lines[-1])
        
    except subprocess.CalledProcessError as e:
        print(f"[Error] Node.js scraper gagal: {e.stderr}")
        return None
    except Exception as e:
        print(f"[Error] Gagal menjalankan Node.js (Pastikan terinstall): {e}")
        return None
