try:
    with open('verify_log.txt', 'r', encoding='utf-16') as f:
        print(f.read())
except Exception as e:
    try:
        with open('verify_log.txt', 'r', encoding='utf-8') as f:
            print(f.read())
    except Exception as e2:
        print(f"Failed to read log: {e2}")
