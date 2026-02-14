#!/usr/bin/env python3
"""测试限流功能"""
import urllib.request
import urllib.parse
import time
import sys

base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8022"
timeout_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 2

# 创建 cookie jar
cookie_jar = {}

def make_request(url, cookie_jar):
    """发送请求并更新 cookie"""
    req = urllib.request.Request(url)
    if cookie_jar:
        req.add_header("Cookie", f"joygate_sandbox={cookie_jar.get('joygate_sandbox', '')}")
    
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            # 读取 Set-Cookie 头
            set_cookie = resp.headers.get("Set-Cookie", "")
            if "joygate_sandbox=" in set_cookie:
                # 解析 cookie
                for part in set_cookie.split(";"):
                    if "joygate_sandbox=" in part:
                        cookie_value = part.split("=")[1].strip()
                        cookie_jar["joygate_sandbox"] = cookie_value
                        break
            
            body = resp.read().decode("utf-8")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8") if e.fp else ""
    except Exception as e:
        return 0, str(e)

# 快速发送请求测试限流
print("Testing rate limit...")
count_200 = 0
count_429 = 0
start_time = time.time()

for i in range(1, 300):
    status, body = make_request(f"{base_url}/dashboard/incidents_daily", cookie_jar)
    if status == 200:
        count_200 += 1
    elif status == 429:
        count_429 += 1
        print(f"Got 429 at request {i}")
        break
    
    # 每 50 个请求打印一次进度
    if i % 50 == 0:
        elapsed = time.time() - start_time
        print(f"Request {i}: 200={count_200}, 429={count_429}, elapsed={elapsed:.2f}s")

elapsed = time.time() - start_time
print(f"\nFinal: Total requests={i}, 200={count_200}, 429={count_429}, elapsed={elapsed:.2f}s")

if count_429 > 0:
    print("Rate limit test: PASS (got 429)")
    sys.exit(0)
else:
    print("Rate limit test: FAIL (no 429 received)")
    sys.exit(1)
