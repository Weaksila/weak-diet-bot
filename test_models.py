import os
import asyncio
from dotenv import load_dotenv

# Load env variables
load_dotenv()

async def test_fallback():
    # Import function and global variables
    from bot import generate_content_with_fallback, api_keys
    print(f"Loaded API keys: {len(api_keys)}")
    
    # 1. Test Text Prompt
    print("\n--- Testing Text Fallback (is_vip=True) ---")
    try:
        resp = await generate_content_with_fallback(["Say hello in 3 words."], is_vip=True)
        print(f"SUCCESS: {resp.text.strip()}")
    except Exception as e:
        print(f"FAILED: {e}")
        
    print("\n--- Testing Text Fallback (is_vip=False) ---")
    try:
        resp = await generate_content_with_fallback(["Say hello in 3 words."], is_vip=False)
        print(f"SUCCESS: {resp.text.strip()}")
    except Exception as e:
        print(f"FAILED: {e}")

    # 2. Test Image Prompt
    dummy_jpeg = b'\xff\xd8\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
    contents = ["What is this? Describe in 3 words.", {"mime_type": "image/jpeg", "data": dummy_jpeg}]
    
    print("\n--- Testing Multimodal Fallback ---")
    try:
        resp = await generate_content_with_fallback(contents, is_vip=True)
        print(f"SUCCESS: {resp.text.strip()}")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_fallback())





