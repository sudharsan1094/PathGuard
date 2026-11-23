import time
from agent.llm import GeminiClient

def main():
    print("1. Initializing Gemini client...", flush=True)
    llm = GeminiClient()

    print(f"2. Client initialized. Model: {llm.model}", flush=True)
    print("3. Sending request to Gemini...", flush=True)

    start = time.time()

    try:
        response = llm.complete(
            system="You are a concise programming assistant.",
            user="Reply with exactly: GEMINI_OK",
        )

        print(f"4. Response received in {time.time() - start:.2f} seconds.")
        print(response)

    except Exception as error:
        print(f"API ERROR: {type(error).__name__}: {error}")

if __name__ == "__main__":
    main()