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

sr = 16000
t = np.linspace(0, 0.8, int(sr * 0.8), False)
audio_part = (np.sin(350 * 2 * np.pi * t) * 4000).astype(np.int16).tobytes()

async def test_3_audio_turns():
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

        async def listener():
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc:
                            if sc.output_transcription:
                                print(sc.output_transcription.text, end="", flush=True)
                            if sc.turn_complete:
                                print(f" [DONE in {time.time()-t_turn:.2f}s]\n", flush=True)
                except Exception as e:
                    break

        asyncio.create_task(listener())

        for i in range(1, 4):
            print(f"--- Sending Audio Turn {i} ---")
            t_turn = time.time()
            await session.send_client_content(
                turns=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=audio_part,
                                    mime_type="audio/pcm;rate=16000"
                                )
                            )
                        ]
                    )
                ],
                turn_complete=True
            )
            await asyncio.sleep(3.5)

asyncio.run(test_3_audio_turns())
