import os
import json
import asyncio
import time
import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

async def test_mic_turns():
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
            async for msg in session.receive():
                sc = msg.server_content
                if sc:
                    if sc.output_transcription:
                        print("RECV:", sc.output_transcription.text, flush=True)
                    if sc.turn_complete:
                        print(">> TURN COMPLETE <<", flush=True)

        asyncio.create_task(reader())

        # Test sending audio chunks
        for i in range(1, 3):
            print(f"\n--- Turn {i}: Sending 1 second of speech tone ---")
            t0 = time.time()
            sr = 16000
            # 1 second of 400Hz speech-like harmonic sound
            t = np.linspace(0, 1.0, sr, False)
            tone = (np.sin(200 * 2 * np.pi * t) * 4000 + np.sin(400 * 2 * np.pi * t) * 2000).astype(np.int16).tobytes()

            chunk_size = 1024
            for offset in range(0, len(tone), chunk_size):
                chunk = tone[offset:offset+chunk_size]
                await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.03)

            print("Sending audio_stream_end...")
            await session.send_realtime_input(audio_stream_end=True)
            await asyncio.sleep(5)

asyncio.run(test_mic_turns())
