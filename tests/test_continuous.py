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

async def test_continuous_stream():
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

        async def reader():
            try:
                async for msg in session.receive():
                    sc = msg.server_content
                    if sc:
                        if sc.output_transcription:
                            print("RECV:", sc.output_transcription.text, flush=True)
                        if sc.turn_complete:
                            print(">> TURN COMPLETE <<", flush=True)
            except Exception as e:
                print("Reader stopped with:", type(e), e)

        rtask = asyncio.create_task(reader())

        # Stream silence (zeroes) continuously, but inject two speech bursts!
        sr = 16000
        silence_chunk = np.zeros(512, dtype=np.int16).tobytes()

        print("Streaming background audio...")
        for i in range(1, 4):
            print(f"\n--- Burst {i}: User speaks ---")
            # Send 1 second of speech tone
            t = np.linspace(0, 0.8, int(sr * 0.8), False)
            tone = (np.sin(300 * 2 * np.pi * t) * 5000).astype(np.int16).tobytes()
            for off in range(0, len(tone), 1024):
                await session.send_realtime_input(audio=types.Blob(data=tone[off:off+1024], mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.03)

            print("User is silent for 3 seconds...")
            for _ in range(50):
                await session.send_realtime_input(audio=types.Blob(data=silence_chunk, mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.05)

        rtask.cancel()

asyncio.run(test_continuous_stream())
