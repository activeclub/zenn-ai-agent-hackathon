### カメラの動作確認
```
rpicam-jpeg --output test.jpg
```

### PulseAudioのAEC(Acoustic Echo Cancellation)をロード
```
pactl load-module module-echo-cancel aec_method=webrtc 
```