import os
import json
import asyncio
import time
import numpy as np
from google import genai
from google.genai import types

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

# Generate 1.0s of simple audio tone
sr = 16000
t = np.linspace(0, 1.0, sr, False)
tone_bytes = (np.sin(300 * 2 * np.pi * t) * 4000).astype(np.int16).tobytes()

async def test_audio_client_content():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко на русском языке.")]
        )
    )

    print("Connecting to gemini-3.8-live...")
    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def listener():
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc:
                            if sc.output_transcription:
                                print(f"TRANSCRIPT: {sc.output_transcription.text}", flush=True)
                            if sc.turn_complete:
                                print(">> TURN COMPLETE <<\n", flush=True)
                except Exception as e:
                    print("Listener finished:", e)
                    break

        asyncio.create_task(listener())

        print("Testing sending audio Part via send_client_content...")
        t0 = time.time()
        try:
            await session.send_client_content(
                turns=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=tone_bytes,
                                    mime_type="audio/pcm;rate=16000"
                                )
                            )
                        ]
                    )
                ],
                turn_complete=True
            )
            print("Successfully sent audio via send_client_content!")
        except Exception as e:
            print("Failed to send audio via send_client_content:", e)

        await asyncio.sleep(5)

asyncio.run(test_audio_client_content())
