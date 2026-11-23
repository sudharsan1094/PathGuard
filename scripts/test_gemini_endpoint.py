import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
model = os.getenv("GEMINI_MODEL")

print(f"Testing model: {model}", flush=True)
print("Sending request...", flush=True)

try:
    response = client.models.generate_content(
        model=model,
        contents="Reply with exactly: GEMINI_OK",
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=30,
        ),
    )

    print("Response:", response.text)

except Exception as error:
    print(f"Error type: {type(error).__name__}")
    print(f"Error details: {error}")