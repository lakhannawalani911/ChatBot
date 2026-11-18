import sys
# sys.path.append(r"C:\Users\lakha\Visual Studio project\chatbot\ChatBot")
# sys.path.append(r"C:\Users\lakha\Visual Studio project\chatbot\ChatBot\app")
from app.cache import ResponseCache    

cache = ResponseCache(ttl_seconds=3)
print("===cache demo ====\n")
result = cache.get(query="what is python")
print(f"first lookup {result} (miss nothing cached yet)")
cache.set("what is Python","python is programming language")
print("result in cached")
result = cache.get("what is python")
print(f"3  Csecond lookup {result}")
print(cache.stats)