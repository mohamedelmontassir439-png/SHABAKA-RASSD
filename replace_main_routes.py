from pathlib import Path

path = Path('main.py')
text = path.read_text(encoding='utf-8')
marker = '# ══════════════════════════════════════════════════════════════════\n# PUBLIC ROUTES'
idx = text.find(marker)
if idx == -1:
    raise SystemExit('marker not found')
new_tail = "\nfrom app.routes import public_router, auth_router, user_router, admin_router, api_router\n\napp.include_router(public_router)\napp.include_router(auth_router)\napp.include_router(user_router)\napp.include_router(admin_router)\napp.include_router(api_router)\n"
text = text[:idx] + new_tail
path.write_text(text, encoding='utf-8')
print('main.py route section replaced')
