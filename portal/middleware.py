from django.http import JsonResponse
from django.core.exceptions import DisallowedHost

class Guard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request.get_host()
        except DisallowedHost:
            return JsonResponse({'error': '请求域名不在允许列表中'}, status=403)
        if request.headers.get('Sec-Fetch-Site') == 'cross-site' and request.method != 'GET':
            return JsonResponse({'error': '请在本站页面提交操作'}, status=403)
        response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        response['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response['Referrer-Policy'] = 'same-origin'
        return response
