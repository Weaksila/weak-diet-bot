import os
import wave
import asyncio
from dotenv import load_dotenv
import google.generativeai as genai

# Load env variables
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def create_valid_wav():
    # Create a 1-second silent WAV file
    wav_path = "silent.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2) # 16-bit
        w.setframerate(16000) # 16kHz
        # Write 1 second of silence (16000 samples of 0)
        w.writeframes(b'\x00' * 32000)
    return wav_path

async def test_audio():
    wav_path = create_valid_wav()
    with open(wav_path, "rb") as f:
        audio_data = f.read()
    
    models = ['gemini-3.1-flash-lite', 'gemini-2.5-flash-lite']
    
    print("--- Testing Valid Audio Input ---")
    for model_name in models:
        print(f"Testing audio on {model_name}...")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                ["Describe this audio or say if it is silent.", {"mime_type": "audio/wav", "data": audio_data}],
                request_options={"timeout": 15.0}
            )
            print(f"SUCCESS {model_name}: {response.text.strip()}")
        except Exception as e:
            print(f"FAILED {model_name}: {e}")
            
    # Clean up
    if os.path.exists(wav_path):
        os.remove(wav_path)

if __name__ == "__main__":
    asyncio.run(test_audio())






