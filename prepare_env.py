from pathlib import Path
import secrets
import sys

def main():
    domain = input('输入此网站的实际域名（不带 https://）：').strip().lower()
    if not domain or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in domain) or '..' in domain or domain.startswith('.'):
        raise SystemExit('域名格式不正确')
    target = Path('.env')
    if target.exists():
        raise SystemExit('.env 已存在，请直接编辑它，避免重置现有会话密钥')
    value = '\n'.join(['LD_MODE=cloud', 'LD_SECRET_KEY=' + secrets.token_urlsafe(48),
        'LD_ALLOWED_HOSTS=' + domain + ',127.0.0.1,localhost',
        'LD_CSRF_ORIGINS=https://' + domain, 'LD_TRUST_PROXY=1', 'LD_CLIENT_IP_HEADER=X-Real-IP',
        'APP_PORT=' + ('8876' if (Path(__file__).resolve().parent / 'ldcell').exists() else '8765'), ''])
    with target.open('x', encoding='utf-8') as stream:
        stream.write(value)
    target.chmod(0o600)
    print('配置已保存到 .env，请勿提交到 Git 或发送给他人。APP_PORT 可按项目修改。')

if __name__ == '__main__':
    main()
