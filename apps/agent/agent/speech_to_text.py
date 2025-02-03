import io
import queue
import re
import sys
import wave

import pyaudio
from google.cloud import speech
import google.generativeai as genai
from google.genai.types import Part, GenerateContentConfig, Blob
from google import genai as genai2
from agent.storage import bucket

from agent.config import config

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

genai.configure(api_key=config.gemini_api_key)


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


def main() -> None:
    """Transcribe speech from audio file."""
    google_speech = GoogleSpeech()

    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        responses = google_speech.recognize(audio_generator)
        listen_print_loop(responses)


async def main2() -> None:
    from google.oauth2 import service_account
    from prisma import Prisma

    filename = "2666599b-e454-48f9-b752-6720e00dfe27.wav"
    blob = bucket.blob(filename)
    audio_bytes = blob.download_as_bytes()

    ##### Speech to Text
    speech_client = speech.SpeechAsyncClient(
        credentials=service_account.Credentials.from_service_account_file(
            config.service_account_key_path
        )
    )
    speech_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="ja-JP",
    )
    # speech_config = cloud_speech.RecognitionConfig(
    #     auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
    #     # encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
    #     # sample_rate_hertz=16000,
    #     language_codes=["ja-JP"],
    #     model="latest_long",
    # )

    # audio = speech.RecognitionAudio(content=Base64.decode(message.contentAudio))

    audio = speech.RecognitionAudio(
        # content=data["audio"],
        uri=f"gs://{config.cloud_storage_bucket}/{filename}",
    )

    ret = await speech_client.recognize(config=speech_config, audio=audio)

    # request = cloud_speech.RecognizeRequest(
    #     recognizer="projects/swift-handler-446606-q0/locations/global/recognizers/_",
    #     config=speech_config,
    #     content=Base64.decode(message.contentAudio),
    # )
    # ret = speech_client.recognize(request=request)

    print(ret)
    #####

    ##### google-generativeai
    # model = genai.GenerativeModel("gemini-2.0-flash-exp")
    # prompt = "Generate a transcript of the speech in Japanese."
    # response = model.generate_content(
    #     [
    #         prompt,
    #         {
    #             "mime_type": "audio/wav",
    #             "data": audio_bytes,
    #         },
    #     ]
    # )
    # print(response.text)
    #####

    ##### google-genai
    client = genai2.client.Client(
        api_key=config.gemini_api_key,
    )
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
        config=GenerateContentConfig(
            system_instruction=[
                "Generate a transcript of the speech in Japanese.",
            ]
        ),
    )

    print(response.text)
    #####


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


if __name__ == "__main__":
    # main()
    import asyncio

    asyncio.run(main2())
