import asyncio
import base64
import io
import traceback
import uuid

import cv2
import numpy as np
import PIL.Image
import pyaudio
from google import genai
from google.cloud import speech
from google.oauth2 import service_account
from prisma import Prisma
from prisma.models import Message, User
from google.genai.types import (
    LiveConnectConfig,
    SpeechConfig,
    VoiceConfig,
    PrebuiltVoiceConfig,
)

from agent.config import config as app_config
from agent.speech import speak_from_bytes
from agent.speech_to_text import pcm_to_wav_bytes
from agent.storage import bucket

FORMAT = pyaudio.paInt16
CHANNELS = 1  # monaural
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024


async def text2text(session: object):
    message = input("User> ")
    await session.send(message, end_of_turn=True)

    async for response in session.receive():
        if response.text is None:
            continue
        print(response.text, end="")


async def text2audio(session: object):
    message = input("User> ")
    await session.send(message, end_of_turn=True)

    audio_data = []
    async for message in session.receive():
        if message.server_content.model_turn:
            for part in message.server_content.model_turn.parts:
                if part.inline_data:
                    audio_data.append(part.inline_data.data)
    if audio_data:
        speak_from_bytes(b"".join(audio_data), sample_rate=24_000)


class AudioLoop:
    def __init__(self, session):
        self.session = session

        self.audio_in_queue = None
        self.out_queue = None
        self.db_queue = None

        self.audio_interface = pyaudio.PyAudio()
        self.audio_stream = None

        self.is_system_speaking = False

        self.speech = speech.SpeechAsyncClient(
            credentials=service_account.Credentials.from_service_account_file(
                app_config.service_account_key_path
            )
        )

        try:
            from libcamera import controls
            from picamera2 import Picamera2

            self.picam2 = Picamera2()
            sensor_modes = self.picam2.sensor_modes
            print("=== sensor_modes ===")
            print(sensor_modes)
            mode = sensor_modes[0]

            camera_controls = {
                "AfMode": controls.AfModeEnum.Continuous,
            }
            preview_config = self.picam2.create_preview_configuration(
                main={
                    "format": "XRGB8888",
                    "size": (1920, 1080),
                },
                # buffer_count=4,
                controls=camera_controls,
                raw=mode,
            )
            self.picam2.configure(preview_config)
            config = self.picam2.camera_configuration()
            print("=== camera config ===")
            print(config)

            self.picam2.start(config=preview_config)
            self.picam2.set_controls({"ScalerCrop": mode["crop_limits"]})

            metadata = self.picam2.capture_metadata()
            print("=== metadata ===")
            print(metadata)
        except ModuleNotFoundError:
            print("libcamera or picamera2 is not installed.")
            self.picam2 = None

    async def send_text(self):
        while True:
            text = await asyncio.to_thread(input, "User> ")
            if text.lower() == "q":
                break
            await self.session.send(input=text or ".", end_of_turn=True)

    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg)

    async def save_db(self):
        language_code = "ja-JP"  # a BCP-47 language tag
        speech_config_system = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RECEIVE_SAMPLE_RATE,
            language_code=language_code,
        )
        speech_config_user = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SEND_SAMPLE_RATE,
            language_code=language_code,
        )
        while True:
            data = await self.db_queue.get()
            speaker = data["speaker"]

            audio_id = str(uuid.uuid4())
            blob = bucket.blob(f"{audio_id}.wav")

            if speaker == "SYSTEM":
                wav_bytes = pcm_to_wav_bytes(
                    data["audio"],
                    channels=CHANNELS,
                    sample_rate=RECEIVE_SAMPLE_RATE,
                    sample_width=2,  # 16bit
                )
                speech_config = speech_config_system
            elif speaker == "USER":
                wav_bytes = pcm_to_wav_bytes(
                    data["audio"],
                    channels=CHANNELS,
                    sample_rate=SEND_SAMPLE_RATE,
                    sample_width=2,  # 16bit
                )
                speech_config = speech_config_user
            else:
                raise ValueError(f"Invalid speaker: {speaker}")

            blob.upload_from_string(wav_bytes, content_type="audio/wav")
            audio = speech.RecognitionAudio(
                # content=data["audio"],
                uri=f"gs://{app_config.cloud_storage_bucket}/{blob.name}",
            )
            response = await self.speech.recognize(config=speech_config, audio=audio)
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript
            await Message.prisma().create(
                {
                    "id": audio_id,
                    "contentURL": blob.public_url,
                    "contentTranscript": transcript,
                    "speaker": speaker,
                }
            )

    async def listen_audio(self):
        mic_info = self.audio_interface.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            self.audio_interface.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )

        if __debug__:
            kwargs = {"exception_on_overflow": False}
        else:
            kwargs = {}

        turn_block = b""
        silent_chnks = 0
        while True:
            # システムが話しだしたら、それまでの入力を保存して音声入力を無視する
            if self.is_system_speaking:
                if turn_block:
                    self.db_queue.put_nowait(
                        {"audio": turn_block, "speaker": "USER"}
                    )
                    turn_block = b""
                continue

            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)

            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

            audio_data = np.frombuffer(data, dtype=np.int16)
            mean_abs_amplitude = np.abs(audio_data).mean()

            if mean_abs_amplitude > 500:
                turn_block += data
                silent_chnks = 0
            else:
                silent_chnks += 1
                # 一定期間以上の無音区間があれば、ターンの終了判定
                silent_sample_num = silent_chnks * CHUNK_SIZE * CHANNELS
                if silent_sample_num >= SEND_SAMPLE_RATE * 3:
                    if turn_block:
                        self.db_queue.put_nowait(
                            {"audio": turn_block, "speaker": "USER"}
                        )
                        turn_block = b""

    def _get_frame(self, frame_rgb):
        img = PIL.Image.fromarray(frame_rgb)  # Now using RGB frame
        img.thumbnail([1024, 1024])

        image_io = io.BytesIO()
        img.save(image_io, format="jpeg")
        image_io.seek(0)

        mime_type = "image/jpeg"
        image_bytes = image_io.read()
        return {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}

    async def get_frames(self):
        if not self.picam2:
            # This takes about a second, and will block the whole program
            # causing the audio pipeline to overflow if you don't to_thread it.
            cap = await asyncio.to_thread(
                cv2.VideoCapture,
                0,  # 0 represents the default camera
            )
            # Prevent `tryIoctl VIDEOIO(V4L2:/dev/video0): select() timeout.` error
            # ref: https://stackoverflow.com/questions/69575185/raspberry-pi-3-video-error-select-timeout-ubuntu
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))

        while True:
            if self.picam2:
                frame = self.picam2.capture_array()
                # 画像が3チャンネル以外の場合は3チャンネルに変換する
                channels = 1 if len(frame.shape) == 2 else frame.shape[2]
                if channels == 1:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                if channels == 4:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                frame_data = await asyncio.to_thread(self._get_frame, frame_rgb)
            else:
                ret, frame = cap.read()
                if not ret:
                    break
                # Fix: Convert BGR to RGB color space
                # OpenCV captures in BGR but PIL expects RGB format
                # This prevents the blue tint in the video feed
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_data = await asyncio.to_thread(self._get_frame, frame_rgb)

            await asyncio.sleep(2.0)

            await self.out_queue.put(frame_data)

        # Release the VideoCapture object
        cap.release()

    async def receive_audio(self):
        "Background task to reads from the websocket and write pcm chunks to the output queue"
        while True:
            turn = self.session.receive()
            turn_block = b""
            async for response in turn:
                if data := response.data:
                    self.is_system_speaking = True
                    self.audio_in_queue.put_nowait(data)
                    has_nonzero = any(b != 0 for b in data)
                    if not has_nonzero:
                        self.db_queue.put_nowait(
                            {"audio": turn_block, "speaker": "SYSTEM"}
                        )
                    else:
                        turn_block += data
                    continue
                if text := response.text:
                    print(text, end="")

            # If you interrupt the model, it sends a turn_complete.
            # For interruptions to work, we need to stop playback.
            # So empty out the audio queue because it may have loaded
            # much more audio than has played yet.
            # while not self.audio_in_queue.empty():
            #     self.audio_in_queue.get_nowait()

            self.is_system_speaking = False

    async def play_audio(self):
        stream = await asyncio.to_thread(
            self.audio_interface.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        while True:
            bytestream = await self.audio_in_queue.get()
            await asyncio.to_thread(stream.write, bytestream)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as tg:
                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)
                self.db_queue = asyncio.Queue()

                send_text_task = tg.create_task(self.send_text())
                tg.create_task(self.get_frames())
                tg.create_task(self.listen_audio())
                tg.create_task(self.send_realtime())
                tg.create_task(self.save_db())

                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())

                await send_text_task
                raise asyncio.CancelledError("User requested exit")
        except asyncio.CancelledError:
            pass
        except ExceptionGroup as EG:
            self.audio_stream.close()
            if self.picam2:
                self.picam2.stop()
            traceback.print_exception(EG)


async def main():
    client = genai.client.Client(
        api_key=app_config.gemini_api_key,
        http_options={"api_version": "v1alpha"},
    )

    # available_models = await client.aio.models.list(config={"page_size": 5})
    # print(available_models.page)

    prisma = Prisma(auto_register=True)

    try:
        await prisma.connect()

        user = await User.prisma().find_first()
        setting = await prisma.setting.find_first(
            where={"userId": user.id},
        )

        model_id = "gemini-2.0-flash-exp"
        config = LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction={
                "parts": [
                    {"text": setting.trait},
                    # {"text": "Please answer concisely in Japanese."},
                    # {"text": "Please answer concisely in Japanese so that even a 5-year-old child can understand."},
                ]
            },
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
        )

        async with client.aio.live.connect(model=model_id, config=config) as session:
            await AudioLoop(session).run()
            # while True:
            #     await text2audio(session)
    except Exception as e:
        print(e)
    finally:
        await prisma.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
