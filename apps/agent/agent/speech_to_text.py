from typing import Optional
import io
import queue
import re
import sys
import wave

import pyaudio
from google.cloud import speech, speech_v2
from google.oauth2 import service_account
from google.genai.types import Part

from agent.config import config
from agent.genai import genai_client
from agent.storage import bucket

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

credentials = service_account.Credentials.from_service_account_file(
    config.service_account_key_path
)
speech_client = speech.SpeechAsyncClient(credentials=credentials)
speech_v2_client = speech_v2.SpeechAsyncClient(credentials=credentials)


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self: object, rate: int = RATE, chunk: int = CHUNK) -> None:
        """The audio -- and generator -- is guaranteed to be on the main thread."""
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self: object) -> object:
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(
        self: object,
        type: object,
        value: object,
        traceback: object,
    ) -> None:
        """Closes the stream, regardless of whether the connection was lost or not."""
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(
        self: object,
        in_data: object,
        frame_count: int,
        time_info: object,
        status_flags: object,
    ) -> object:
        """Continuously collect data from the audio stream, into the buffer.

        Args:
            in_data: The audio data as a bytes object
            frame_count: The number of frames captured
            time_info: The time information
            status_flags: The status flags

        Returns:
            The audio data as a bytes object
        """
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self: object) -> object:
        """Generates audio chunks from the stream of audio data in chunks.

        Args:
            self: The MicrophoneStream object

        Returns:
            A generator that outputs audio chunks.
        """
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)


def listen_print_loop(responses: object) -> str:
    """Iterates through server responses and prints them.

    The responses passed is a generator that will block until a response
    is provided by the server.

    Each response may contain multiple results, and each result may contain
    multiple alternatives; for details, see https://goo.gl/tjCPAU.  Here we
    print only the transcription for the top alternative of the top result.

    In this case, responses are provided for interim results as well. If the
    response is an interim one, print a line feed at the end of it, to allow
    the next result to overwrite it, until the response is a final one. For the
    final one, print a newline to preserve the finalized transcription.

    Args:
        responses: List of server responses

    Returns:
        The transcribed text.
    """
    num_chars_printed = 0
    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        # Display the transcription of the top alternative.
        transcript = result.alternatives[0].transcript

        # Display interim results, but with a carriage return at the end of the
        # line, so subsequent lines will overwrite them.
        #
        # If the previous result was longer than this one, we need to print
        # some extra spaces to overwrite the previous result
        overwrite_chars = " " * (num_chars_printed - len(transcript))

        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + "\r")
            sys.stdout.flush()

            num_chars_printed = len(transcript)

        else:
            print(transcript + overwrite_chars)

            # Exit recognition if any of the transcribed phrases could be
            # one of our keywords.
            if re.search(r"\b(exit|quit)\b", transcript, re.I):
                print("Exiting..")
                break

            num_chars_printed = 0

    return transcript


class GoogleSpeech:
    def __init__(self):
        # See http://g.co/cloud/speech/docs/languages
        # for a list of supported languages.
        language_code = "ja-JP"  # a BCP-47 language tag

        self.client = speech.SpeechClient()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=language_code,
        )
        self.streaming_config = speech.StreamingRecognitionConfig(
            config=config, interim_results=True
        )

    def recognize(self, audio_generator: object) -> object:
        requests = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )

        responses = self.client.streaming_recognize(self.streaming_config, requests)
        return responses


async def main() -> None:
    pa = pyaudio.PyAudio()
    mic_info = pa.get_default_input_device_info()
    print(mic_info)

    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        print(i, info["name"])

    filename = "8afd47b0-9801-4478-b148-0e9d8cae115f.wav"
    blob = bucket.blob(filename)
    audio_bytes = blob.download_as_bytes()

    ##### Speech to Text
    # ret = await stt_google(audio_bytes=audio_bytes)
    # print(ret)
    #####

    # ret = await stt_google_v2(audio_bytes=audio_bytes)
    # print(ret)

    ##### google-genai
    # ret = await stt_genai(
    #     audio_bytes=audio_bytes,
    #     storage_uri=f"gs://{config.cloud_storage_bucket}/{filename}",
    # )
    # print(ret)
    #####

    # google_speech = GoogleSpeech()
    # with MicrophoneStream(RATE, CHUNK) as stream:
    #     audio_generator = stream.generator()
    #     responses = google_speech.recognize(audio_generator)
    #     listen_print_loop(responses)


async def stt_google(
    sample_rate: int = 16_000,
    language_code: str = "ja-JP",
    audio_bytes: Optional[bytes] = None,
    storage_uri: Optional[str] = None,
) -> str:
    speech_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,
        language_code=language_code,
    )

    audio = speech.RecognitionAudio(
        content=audio_bytes,
        uri=storage_uri,
    )

    response = await speech_client.recognize(config=speech_config, audio=audio)

    transcript = ""
    for result in response.results:
        transcript += result.alternatives[0].transcript

    return transcript


async def stt_google_v2(audio_bytes: Optional[bytes] = None) -> str:
    speech_config = speech_v2.types.cloud_speech.RecognitionConfig(
        auto_decoding_config=speech_v2.types.AutoDetectDecodingConfig(),
        language_codes=["ja-JP"],
        model="latest_long",
    )

    request = speech_v2.types.cloud_speech.RecognizeRequest(
        recognizer=f"projects/{credentials.project_id}/locations/global/recognizers/_",
        config=speech_config,
        content=audio_bytes,
    )
    response = await speech_v2_client.recognize(request=request)

    transcript = ""
    for result in response.results:
        transcript += result.alternatives[0].transcript

    return transcript


async def stt_genai(
    audio_bytes: Optional[bytes] = None, storage_uri: Optional[str] = None
) -> str:
    contents = [Part.from_text(text="Generate a transcript of the speech in Japanese.")]

    if audio_bytes:
        contents.append(Part.from_bytes(data=audio_bytes, mime_type="audio/wav"))
    elif storage_uri:
        contents.append(Part.from_uri(file_uri=storage_uri, mime_type="audio/wav"))

    response = await genai_client.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=contents,
        # config=GenerateContentConfig(
        #     system_instruction=[
        #         "Generate a transcript of the speech in Japanese.",
        #     ]
        # ),
    )

    return response.text


def pcm_to_wav_bytes(pcm_bytes, sample_rate=16000, channels=1, sample_width=2):
    """
    PCMバイトデータをWAVバイトデータに変換します。

    :param pcm_bytes: PCM形式の音声データ
    :param sample_rate: サンプルレート
    :param channels: チャンネル数(モノラル=1、ステレオ=2)
    :param sample_width: サンプル幅(バイト単位、ex. 16ビット=2)
    :return: WAV形式の音声データ
    """
    with io.BytesIO() as wav_io:
        # WAVファイルの書き込み用にwaveモジュールを使用
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)

        # バイトデータとして取得
        wav_bytes = wav_io.getvalue()

    return wav_bytes


def open_wav(file_path: str):
    with wave.open(file_path) as f:
        metadata = f.getparams()
        frames = f.readframes(metadata.nframes)
        print(metadata)
        print(frames)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
