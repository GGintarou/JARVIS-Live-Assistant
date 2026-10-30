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

async def test_full_audio_turn_pipeline():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко в 1 предложение на русском языке.")]
        )
    )

    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def listener():
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc:
                            if sc.output_transcription:
                                print(f"JARVIS: {sc.output_transcription.text}")
                            if sc.turn_complete:
                                print(">> Turn complete! <<")
                except Exception as e:
                    break

        asyncio.create_task(listener())

        # Test sending an audio turn of silence / tone
        sr = 16000
        t = np.linspace(0, 0.6, int(sr * 0.6), False)
        tone = (np.sin(300 * 2 * np.pi * t) * 4000).astype(np.int16).tobytes()

        print("Sending audio turn...")
        await session.send_client_content(
            turns=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=tone,
                                mime_type="audio/pcm;rate=16000"
                            )
                        )
                    ]
                )
            ],
            turn_complete=True
        )
        await asyncio.sleep(4)

asyncio.run(test_full_audio_turn_pipeline())
