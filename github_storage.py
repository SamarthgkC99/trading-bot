# FILE: github_storage.py
import os
import json
import base64
import requests
from datetime import datetime

class GitHubStorage:
    def __init__(self):
        self.token = os.environ.get('GITHUB_TOKEN')
        self.repo_url = os.environ.get('DATA_REPO_URL')
        self.api_base = "https://api.github.com"
        
        if not self.token or not self.repo_url:
            raise ValueError("GITHUB_TOKEN and DATA_REPO_URL environment variables must be set.")
            
        parts = self.repo_url.strip('/').split('/')
        self.owner, self.repo = parts[-2], parts[-1]
        
    def _get_headers(self):
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
    
    def _get_file_info(self, path):
        url = f"{self.api_base}/repos/{self.owner}/{self.repo}/contents/{path}"
        response = requests.get(url, headers=self._get_headers()})
        
        if response.status_code == 200:
            return response.json()
        return None

    def read_file(self, path):
        try:
            file_info = self._get_file_info(path)
            if file_info and file_info.get('content'):
                content = base64.b64decode(file_info['content']).decode('utf-8')
                return json.loads(content)
        except Exception as e:
            print(f"Error reading {path} from GitHub: {e}")
        return None
    
    def write_file(self, path, data):
        try:
            url = f"{self.api_base}/repos/{self.owner}/{self.repo}/contents/{path}"
            file_info = self._get_file_info(path)
            
            json_data = json.dumps(data, indent=4)
            content_bytes = json_data.encode('utf-8')
            content_b64 = base64.b64encode(content_bytes).decode('utf-8')
            
            payload = {
                "message": f"Automated update: {path} at {datetime.now().isoformat()}",
                "content": content_b64
            }
            
            if file_info and file_info.get('sha'):
                payload["sha"] = file_info['sha']
                
            response = requests.put(url, headers=self._get_headers(), json=payload)
            
            if response.status_code in [200, 201]:
                return True
            else:
                print(f"Error writing {path} to GitHub: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Exception during write of {path} to GitHub: {e}")
            return False
