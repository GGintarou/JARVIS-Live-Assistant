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

async def test_other_models():
    for model_name in ["gemini-2.5-flash-native-audio-latest", "gemini-3.1-flash-live-preview"]:
        print(f"\n================ Testing {model_name} ================")
        connect_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        try:
            async with client.aio.live.connect(model=model_name, config=connect_config) as session:
                print(f"Connected to {model_name}")

                async def reader():
                    try:
                        async for msg in session.receive():
                            sc = msg.server_content
                            if sc:
                                if sc.output_transcription:
                                    print(f"[{model_name}] {sc.output_transcription.text}", flush=True)
                                if sc.turn_complete:
                                    print(f"[{model_name}] >> TURN COMPLETE <<", flush=True)
                    except Exception as e:
                        print("Reader error:", e)

                rtask = asyncio.create_task(reader())

                print("Turn 1...")
                await session.send_client_content(
                    turns=[types.Content(role="user", parts=[types.Part(text="Привет, как дела?")])],
                    turn_complete=True
                )
                await asyncio.sleep(4)

                print("Turn 2...")
                await session.send_client_content(
                    turns=[types.Content(role="user", parts=[types.Part(text="Который час?")])],
                    turn_complete=True
                )
                await asyncio.sleep(4)
                rtask.cancel()
        except Exception as e:
            print(f"Model {model_name} failed:", e)

asyncio.run(test_other_models())
