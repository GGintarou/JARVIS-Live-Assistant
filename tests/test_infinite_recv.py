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

async def test_proper_receive_loop():
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

        async def infinite_receive():
            turn_count = 0
            while True:
                turn_count += 1
                print(f"[Starting receive loop for turn {turn_count}]")
                async for msg in session.receive():
                    sc = msg.server_content
                    if sc:
                        if sc.output_transcription:
                            print(sc.output_transcription.text, end="", flush=True)
                        if sc.turn_complete:
                            print(f" [Turn {turn_count} complete!]\n", flush=True)

        rtask = asyncio.create_task(infinite_receive())

        print("--- Sending Turn 1 ---")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Привет, Джарвис!")])],
            turn_complete=True
        )
        await asyncio.sleep(4)

        print("--- Sending Turn 2 ---")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Как твои дела?")])],
            turn_complete=True
        )
        await asyncio.sleep(4)

        print("--- Sending Turn 3 ---")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Скажи погоду на завтра в Москве.")])],
            turn_complete=True
        )
        await asyncio.sleep(4)

        rtask.cancel()

asyncio.run(test_proper_receive_loop())
