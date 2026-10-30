import os
import json
import asyncio
from google import genai
from google.genai import types

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

async def debug_live_session():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко на русском языке.")]
        )
    )

    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def reader():
            try:
                async for msg in session.receive():
                    print("RAW MSG:", msg)
            except Exception as e:
                print("Reader exception:", e)

        rtask = asyncio.create_task(reader())

        print("Sending Turn 1...")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Привет")])],
            turn_complete=True
        )
        await asyncio.sleep(4)

        print("Sending Turn 2...")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Как дела?")])],
            turn_complete=True
        )
        await asyncio.sleep(4)
        rtask.cancel()

asyncio.run(debug_live_session())
