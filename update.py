import os

filepath = 'services/constellation/constellation/backend.py'
with open(filepath, 'r') as f:
    content = f.read()

search_str = """    def check_origin(self, origin: str) -> bool:
        header = self.request.headers.get("Authorization", "").strip()
        if header.lower().startswith("bearer "):
            return True
        if not origin:
            return True
        allowed = self.app_state.settings.allowed_ws_origins
        if not allowed:
            return False
        return _normalize_origin(origin) in allowed"""

replace_str = """    def check_origin(self, origin: str) -> bool:
        if not origin:
            return True
        allowed = self.app_state.settings.allowed_ws_origins
        if not allowed:
            return False
        return _normalize_origin(origin) in allowed"""

if search_str in content:
    with open(filepath, 'w') as f:
        f.write(content.replace(search_str, replace_str))
    print("Success")
else:
    print("Failed to find search string")
