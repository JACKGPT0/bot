from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import pickle
import os
import re
from bs4 import BeautifulSoup
from html import unescape
import uuid
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configuration
LOGIN_URL = "https://d-group.stats.direct/user-management/auth/login"
SMS_URL = ("https://d-group.stats.direct/sms-records/index?"
           "PartitionSmsInboundAllocationSearch%5Bdate_range%5D=2025-10-21+00%3A00%3A00+-+2025-10-21+23%3A59%3A59"
           "&PartitionSmsInboundAllocationSearch%5Bpartition_crm_id_client%5D=1175")
DASHBOARD_URL = "https://d-group.stats.direct/dashboard"

# Sessions storage
SESSIONS = {}

def create_session():
    """Create a new requests session with proper headers"""
    session = requests.Session()
    
    # Headers to mimic a real browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    })
    
    return session

def get_csrf_from_html(html_text):
    """Extract CSRF token from HTML"""
    soup = BeautifulSoup(html_text, "html.parser")
    inp = soup.find("input", {"name": "_csrf-frontend"})
    return inp["value"] if inp and inp.has_attr("value") else None

def extract_messages(html_text):
    """Extract SMS messages from HTML table"""
    soup = BeautifulSoup(html_text, "html.parser")
    messages = []
    
    for row in soup.select("tbody tr"):
        tds = row.find_all("td")
        cols = [td.get_text(separator=" ", strip=True) for td in tds]
        if not cols:
            continue
            
        raw_message = cols[-1] if cols else ""
        otp, token = extract_otp_and_token(raw_message)
        
        messages.append({
            "date": cols[0] if len(cols) > 0 else "",
            "ref": cols[1] if len(cols) > 1 else "",
            "client": cols[2] if len(cols) > 2 else "",
            "source": cols[3] if len(cols) > 3 else "",
            "destination": cols[4] if len(cols) > 4 else "",
            "raw": raw_message,
            "otp": otp,
            "token": token
        })
    
    return messages

def extract_otp_and_token(raw_text):
    """Extract OTP code and token from message text"""
    if not raw_text:
        return None, None
    
    text = unescape(raw_text)
    otp = None
    token = None
    
    # Extract OTP (6 digits after colon)
    after_colon = text.rpartition(':')[2]
    if after_colon:
        digits = re.findall(r'\d', after_colon)
        if len(digits) >= 6:
            m = re.search(r'(\d\D*\d\D*\d\D*\d\D*\d\D*\d)', after_colon)
            if m:
                seq = re.sub(r'\D', '', m.group(1))
                if len(seq) == 6:
                    otp = f"{seq[:3]}-{seq[3:]}"
    
    # Extract token (alphanumeric 6-24 chars, not all digits)
    tokens = re.findall(r'\b([A-Za-z0-9]{6,24})\b', text)
    for t in reversed(tokens):
        if t.isdigit() and len(t) == 6:
            continue
        if re.search(r'[A-Za-z]', t) and not t.isdigit():
            token = t
            break
    
    return otp, token

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم وكلمة المرور مطلوبان'
            }), 400
        
        session = create_session()
        
        # Step 1: Get login page and CSRF token
        print(f"[LOGIN] Fetching login page for user: {username}")
        r = session.get(LOGIN_URL, timeout=30, allow_redirects=True)
        
        if r.status_code != 200:
            print(f"[LOGIN] Failed to fetch login page: {r.status_code}")
            return jsonify({
                'status': 'error',
                'message': f'فشل في الوصول لصفحة تسجيل الدخول (HTTP {r.status_code})'
            }), 500
        
        csrf_token = get_csrf_from_html(r.text)
        if not csrf_token:
            print("[LOGIN] CSRF token not found")
            return jsonify({
                'status': 'error',
                'message': 'لم يتم العثور على رمز CSRF'
            }), 500
        
        print(f"[LOGIN] CSRF token found: {csrf_token[:10]}...")
        
        # Step 2: Submit login form
        payload = {
            "_csrf-frontend": csrf_token,
            "LoginForm[username]": username,
            "LoginForm[password]": password,
            "LoginForm[rememberMe]": "0"
        }
        
        headers = {
            "Referer": LOGIN_URL,
            "Origin": "https://d-group.stats.direct",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=30, allow_redirects=True)
        
        print(f"[LOGIN] Login POST status: {resp.status_code}")
        print(f"[LOGIN] Final URL: {resp.url}")
        
        # Step 3: Verify login by checking dashboard access
        dashboard_resp = session.get(DASHBOARD_URL, timeout=15)
        
        # Check if we're actually logged in
        if dashboard_resp.status_code != 200:
            print(f"[LOGIN] Cannot access dashboard: {dashboard_resp.status_code}")
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'
            }), 401
        
        # Check if redirected to login page
        if "login" in dashboard_resp.url.lower():
            print("[LOGIN] Redirected to login - authentication failed")
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'
            }), 401
        
        # Check for dashboard content
        if "dashboard" not in dashboard_resp.text.lower():
            print("[LOGIN] Dashboard content not found")
            return jsonify({
                'status': 'error',
                'message': 'فشل في تسجيل الدخول'
            }), 401
        
        print("[LOGIN] Login successful!")
        
        session_id = f"session_{uuid.uuid4().hex}"
        SESSIONS[session_id] = {
            'session': session,
            'username': username,
            'created_at': datetime.now().isoformat(),
            'valid': True
        }
        
        return jsonify({
            'status': 'success',
            'account_id': session_id,
            'username': username,
            'created_at': datetime.now().isoformat(),
            'message': 'تم تسجيل الدخول بنجاح'
        }), 200
        
    except requests.exceptions.Timeout:
        print("[LOGIN ERROR] Request timeout")
        return jsonify({
            'status': 'error',
            'message': 'انتهت مهلة الاتصال بالخادم'
        }), 500
    except requests.exceptions.ConnectionError:
        print("[LOGIN ERROR] Connection error")
        return jsonify({
            'status': 'error',
            'message': 'خطأ في الاتصال بالخادم'
        }), 500
    except Exception as e:
        print(f"[LOGIN ERROR] {e}")
        return jsonify({
            'status': 'error',
            'message': f'خطأ في تسجيل الدخول: {str(e)}'
        }), 500

@app.route('/api/messages/<session_id>', methods=['GET'])
def get_messages(session_id):
    """Get messages for a session"""
    try:
        if session_id not in SESSIONS:
            return jsonify({
                'status': 'error',
                'message': 'جلسة غير صالحة'
            }), 404
        
        session_data = SESSIONS[session_id]
        if not session_data.get('valid'):
            return jsonify({
                'status': 'error',
                'message': 'انتهت صلاحية الجلسة'
            }), 401
        
        session = session_data['session']
        
        print(f"[MESSAGES] Fetching messages for session: {session_id}")
        
        # Fetch SMS page
        r = session.get(SMS_URL, timeout=20)
        
        if r.status_code != 200:
            print(f"[MESSAGES] Failed to fetch: {r.status_code}")
            
            # Invalidate session if unauthorized
            if r.status_code in [302, 401, 403]:
                session_data['valid'] = False
                return jsonify({
                    'status': 'error',
                    'message': 'انتهت صلاحية الجلسة'
                }), 401
            
            return jsonify({
                'status': 'error',
                'message': f'فشل في جلب الرسائل (HTTP {r.status_code})'
            }), 500
        
        # Extract messages
        messages = extract_messages(r.text)
        
        # Filter messages for specific client if needed
        # messages = [m for m in messages if m.get("client", "").strip().lower() == "hazem0100"]
        
        print(f"[MESSAGES] Found {len(messages)} messages")
        
        return jsonify({
            'status': 'success',
            'messages': messages,
            'count': len(messages)
        }), 200
        
    except Exception as e:
        print(f"[MESSAGES ERROR] {e}")
        return jsonify({
            'status': 'error',
            'message': f'خطأ في جلب الرسائل: {str(e)}'
        }), 500

@app.route('/api/logout/<session_id>', methods=['POST'])
def logout(session_id):
    """Logout and invalidate session"""
    try:
        if session_id in SESSIONS:
            SESSIONS[session_id]['valid'] = False
            del SESSIONS[session_id]
        
        return jsonify({
            'status': 'success',
            'message': 'تم تسجيل الخروج بنجاح'
        }), 200
        
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({
            'status': 'error',
            'message': 'خطأ في تسجيل الخروج'
        }), 500

@app.route('/api/status', methods=['GET'])
def status():
    """Get API status"""
    return jsonify({
        'status': 'success',
        'message': 'API is running',
        'active_sessions': len([s for s in SESSIONS.values() if s.get('valid')])
    }), 200

if __name__ == '__main__':
    print("Starting Flask API server...")
    print(f"Using requests library with custom headers")
    print(f"Active sessions will be stored in memory")
    app.run(host='0.0.0.0', port=5000, debug=True)
