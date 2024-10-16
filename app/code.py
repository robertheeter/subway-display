# type: ignore

import time

while True:
    try:
        exec(open("subway.py").read())
    except Exception as e:
        print(f"SUBWAY.PY runtime error, retrying: {e}")
    
    time.sleep(1)
