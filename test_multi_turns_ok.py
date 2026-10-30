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

async def test_multi_turn_voice():
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

        async def infinite_receive():
            turn_idx = 0
            while True:
                turn_idx += 1
                async for msg in session.receive():
                    sc = msg.server_content
                    if sc:
                        if sc.output_transcription:
                            print(sc.output_transcription.text, end="", flush=True)
                        if sc.turn_complete:
                            print(f" [Turn {turn_idx} DONE]\n", flush=True)

        asyncio.create_task(infinite_receive())

        # Test sending 3 speech inputs via send_client_content
        for phrase in ["Привет, Джарвис!", "Какая погода?", "Спасибо, Джарвис!"]:
            print(f"Sending: {phrase}")
            t0 = time.time()
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=phrase)])],
                turn_complete=True
            )
            # Measure time until turn complete or wait
            await asyncio.sleep(3.5)

asyncio.run(test_multi_turn_voice())
