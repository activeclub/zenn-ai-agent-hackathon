import asyncio
import base64
import io
import traceback
import uuid

import cv2
import numpy as np
import PIL.Image
import pyaudio
from google.cloud import speech, speech_v2
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
from agent.genai import genai_client
from agent.speech_to_text import pcm_to_wav_bytes, stt_google, stt_genai
from agent.storage import bucket

FORMAT = pyaudio.paInt16
CHANNELS = 1  # monaural
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024


class AudioLoop:
    def __init__(self, session):
        self.session = session

        self.audio_in_queue = None
        self.out_queue = None
        self.db_queue = None

        self.audio_interface = pyaudio.PyAudio()
        self.audio_stream = None
        print("=== Default input device info ===")
        print(self.audio_interface.get_default_input_device_info())

        self.is_system_speaking = False

        self.google_credentials = service_account.Credentials.from_service_account_file(
            app_config.service_account_key_path
        )
        self.speech = speech.SpeechAsyncClient(credentials=self.google_credentials)
        self.speech_v2 = speech_v2.SpeechAsyncClient(
            credentials=self.google_credentials
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
            elif speaker == "USER":
                wav_bytes = pcm_to_wav_bytes(
                    data["audio"],
                    channels=CHANNELS,
                    sample_rate=SEND_SAMPLE_RATE,
                    sample_width=2,  # 16bit
                )
            else:
                raise ValueError(f"Invalid speaker: {speaker}")

            blob.upload_from_string(wav_bytes, content_type="audio/wav")

            # stt_google()が使えないので直接書く
            speech_config = speech_v2.types.cloud_speech.RecognitionConfig(
                auto_decoding_config=speech_v2.types.AutoDetectDecodingConfig(),
                language_codes=[language_code],
                model="latest_long",
            )
            request = speech_v2.types.cloud_speech.RecognizeRequest(
                recognizer=f"projects/{self.google_credentials.project_id}/locations/global/recognizers/_",
                config=speech_config,
                content=wav_bytes,
            )
            response = await self.speech_v2.recognize(request=request)
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript
            # transcript = await stt_google(
            #     storage_uri=f"gs://{app_config.cloud_storage_bucket}/{blob.name}",
            #     sample_rate=sample_rate,
            #     language_code=language_code,
            # )
            # transcript = await stt_genai(audio_bytes=wav_bytes)

            await Message.prisma().create(
                {
                    "id": audio_id,
                    "contentURL": blob.public_url,
                    "contentTranscript": transcript,
                    "speaker": speaker,
                }
            )

    async def listen_audio(self):
        print("Available input devices:")
        for i in range(self.audio_interface.get_device_count()):
            info = self.audio_interface.get_device_info_by_index(i)
            print(f"{i}: {info['name']}")

        mic_device_index = int(
            input(
                "Please enter the user's microphone input device number (User's speech + system sound mixed): ",
            )
        )

        self.audio_stream = await asyncio.to_thread(
            self.audio_interface.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            # input_device_index=self.audio_interface.get_default_input_device_info()["index"],
            input_device_index=mic_device_index,
            frames_per_buffer=CHUNK_SIZE,
        )

        if __debug__:
            kwargs = {"exception_on_overflow": False}
        else:
            kwargs = {}

        turn_block = b""
        silent_chunks = 0
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)

            # FIXME: dataがユーザーの発話音声データ or システムの発話音声データのどちらかを判定する

            await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

            audio_data = np.frombuffer(data, dtype=np.int16)
            mean_abs_amplitude = np.abs(audio_data).mean()

            if mean_abs_amplitude < 500:
                turn_block += data
                silent_chunks += 1
            else:
                turn_block += data
                silent_chunks = 0

            # 一定期間以上の無音区間があれば、ターンの終了判定
            silent_sample_num = silent_chunks * CHUNK_SIZE * CHANNELS
            if silent_sample_num >= SEND_SAMPLE_RATE * 3 or self.is_system_speaking:
                if len(turn_block) > 2048:
                    self.db_queue.put_nowait({"audio": turn_block, "speaker": "USER"})
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
                    turn_block += data
                if text := response.text:
                    print(text, end="")

            # If you interrupt the model, it sends a turn_complete.
            # For interruptions to work, we need to stop playback.
            # So empty out the audio queue because it may have loaded
            # much more audio than has played yet.
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()

            has_nonzero = any(b != 0 for b in turn_block)
            if has_nonzero:
                self.db_queue.put_nowait({"audio": turn_block, "speaker": "SYSTEM"})

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
                    {
                        "text": f"""{setting.trait}

Please note: The camera and microphone are in close proximity, so any words you speak might be inadvertently picked up and transmitted.
If that happens, please disregard your own spoken words.
Additionally, if the system's voice is transmitted, do not return turn_complete so that it is not recognized as an interruption.
Furthermore, if the received audio contains significant noise and cannot be clearly understood, please ignore it rather than attempting to provide an answer.
"""
                    },
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

        async with genai_client.aio.live.connect(
            model=model_id, config=config
        ) as session:
            await AudioLoop(session).run()
    except Exception as e:
        print(e)
    finally:
        await prisma.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
