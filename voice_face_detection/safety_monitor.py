import os
import speech_recognition as sr
import sounddevice as sd
import numpy as np
import wave
import datetime
import cv2
import requests
import threading
import geocoder
import time
import mysql.connector
from flask import Flask, Response

# Configuration
PHP_BACKEND_URL = "http://localhost/safety_locket/alert.php"
DISTRESS_WORDS = ["help", "scream", "stop", "emergency"]
LOUDNESS_THRESHOLD = 50
STREAMING_ACTIVE = False
RECORDING_DURATION = 30  # Video Recording Duration (Seconds)
AUDIO_RECORDING_DURATION = 30  # Audio Recording Duration (Seconds)

# Create folder for saving recordings
SAVE_FOLDER = "Recordings"
if not os.path.exists(SAVE_FOLDER):
    os.makedirs(SAVE_FOLDER)

# Initialize Flask App
app = Flask(__name__)

# Database Connection
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="safety_locket"
    )

# Get User Location
def get_location():
    try:
        g = geocoder.ip('me')
        return g.latlng if g.latlng else (0, 0)
    except Exception as e:
        print(f"❌ Location Error: {e}")
        return (0, 0)

# Send Alert to PHP Backend
def send_alert(event_type, location):
    data = {"event": event_type, "latitude": location[0], "longitude": location[1]}
    try:
        response = requests.post(PHP_BACKEND_URL, json=data, timeout=5)
        response.raise_for_status()
        print(f"✅ Alert Sent: {event_type}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send alert: {e}")

# Save Audio Recording and Store in Database
def save_audio(audio_data, samplerate):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_filename = os.path.join(SAVE_FOLDER, f"distress_sound_{timestamp}.wav")

    try:
        with wave.open(audio_filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            frames_to_save = int(samplerate * AUDIO_RECORDING_DURATION)
            audio_to_save = audio_data[:frames_to_save]
            wf.writeframes(audio_to_save.astype(np.int16).tobytes())

        print(f"🔴 Audio saved as {audio_filename}")

        # Store in Database
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO recordings (type, filename, timestamp) VALUES (%s, %s, %s)",
                       ("audio", audio_filename, timestamp))
        conn.commit()
        conn.close()

        return audio_filename
    except Exception as e:
        print(f"❌ Audio Save Error: {e}")
        return None

# Detect Audio Triggers (Screaming or Distress Words)
def detect_audio_triggers():
    recognizer = sr.Recognizer()
    audio_buffer = []

    def audio_callback(indata, frames, time_info, status):
        nonlocal audio_buffer
        volume = np.linalg.norm(indata) * 10
        audio_buffer.append(indata.copy())
        max_buffer_size = int(44100 * AUDIO_RECORDING_DURATION / frames)
        if len(audio_buffer) > max_buffer_size:
            audio_buffer.pop(0)

        if volume > LOUDNESS_THRESHOLD:
            print("🔊 Loud Sound Detected!")
            audio_data = np.concatenate(audio_buffer, axis=0)
            save_audio(audio_data[:, 0], 44100)
            send_alert("Loud Sound Detected", get_location())
            start_recording_and_streaming()

    with sd.InputStream(callback=audio_callback, channels=1, samplerate=44100):
        with sr.Microphone() as source:
            while True:
                try:
                    print("🎤 Listening for distress words...")
                    audio = recognizer.listen(source, timeout=5)
                    text = recognizer.recognize_google(audio).lower()
                    print(f"🗣 Recognized: {text}")
                    if any(word in text for word in DISTRESS_WORDS):
                        print("🚨 Distress Word Detected!")
                        send_alert(f"Distress Word '{text}' Detected", get_location())
                        start_recording_and_streaming()
                except (sr.UnknownValueError, sr.RequestError) as e:
                    print(f"🎤 Audio Processing Error: {e}")
                time.sleep(1)

# Record Video with Face Detection and Save to Database
def record_video_with_face_detection():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Error: Could not access camera!")
        return

    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    video_filename = os.path.join(SAVE_FOLDER, f'recording_{timestamp}.avi')
    out = cv2.VideoWriter(video_filename, fourcc, 20.0, (640, 480))
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    start_time = time.time()
    face_detected = False

    while time.time() - start_time < RECORDING_DURATION:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("⚠️ Warning: Empty frame received, retrying...")
            continue

        out.write(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        if len(faces) > 0:
            face_detected = True
            print("👤 Face Detected!")

    cap.release()
    out.release()
    print(f"📹 Video Recorded: {video_filename}")

    # Store in Database
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO recordings (type, filename, timestamp) VALUES (%s, %s, %s)",
                   ("video", video_filename, timestamp))
    conn.commit()
    conn.close()

    if face_detected:
        send_alert("Face Detected in Recording", get_location())

    return video_filename

# Live Streaming
def generate_frames():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Error: Could not access camera for streaming!")
        return

    while STREAMING_ACTIVE:
        success, frame = cap.read()
        if not success:
            continue
        _, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    cap.release()

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# Start Recording and Streaming
def start_recording_and_streaming():
    global STREAMING_ACTIVE
    if not STREAMING_ACTIVE:
        STREAMING_ACTIVE = True
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False), daemon=True).start()
    
    threading.Thread(target=record_video_with_face_detection, daemon=True).start()

# Run the Safety Monitoring System
if __name__ == "__main__":
    print("🚀 Safety Monitoring System Starting...")
    threading.Thread(target=detect_audio_triggers, daemon=True).start()
    while True:
        time.sleep(1)
