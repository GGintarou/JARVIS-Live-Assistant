import os
import json
import asyncio
import time
from google import genai
from google.genai import types

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

async def test_multi_turn_infinite():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко на русском языке.")]
        )
    )

    print("Connecting...")
    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def infinite_listener():
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc:
                            if sc.output_transcription:
                                print(sc.output_transcription.text, end="", flush=True)
                            if sc.turn_complete:
                                print(" [Turn complete]\n", flush=True)
                except Exception as e:
                    print("Listener error:", e)
                    break

        ltask = asyncio.create_task(infinite_listener())

        # Test rapid questions
        queries = ["Привет!", "Сколько будет два плюс два?", "Кто создал Железного Человека?"]
        for q in queries:
            print(f">> USER: {q}")
            t0 = time.time()
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=q)])],
                turn_complete=True
            )
            await asyncio.sleep(4)

        ltask.cancel()

asyncio.run(test_multi_turn_infinite())
