"""
SeñasCL - Dynamic Sign Clip Capture
Records complete landmark sequences (clips) per word for temporal model training.

Usage:
    python capture_dynamic_clip.py --output-dir clips/
    python capture_dynamic_clip.py --output-dir clips/ --words HOLA GRACIAS SI NO

Requires:
    pip install mediapipe opencv-python numpy

Controls:
    SPACE  - Start/stop recording a clip
    ENTER  - Confirm label and save clip
    ESC    - Skip current clip
    q      - Quit
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import mediapipe as mp
    import cv2
    import numpy as np
except ImportError:
    print("Install dependencies: pip install mediapipe opencv-python numpy")
    sys.exit(1)

# Default words for MVP (8-12 words, keeping it small for validation)
DEFAULT_WORDS = [
    "HOLA",        # Hello
    "GRACIAS",     # Thanks
    "POR_FAVOR",   # Please
    "SI",          # Yes
    "NO",          # No
    "YO",          # I/me
    "TU",          # You
    "AYUDA",       # Help
    "BIEN",        # Good
    "TRABAJO",     # Work
]

# Minimum expected frames per clip (~1 second at 30fps)
MIN_FRAMES = 15
# Maximum frames before auto-cut (~3 seconds)
MAX_FRAMES = 90
# Target clips per word
TARGET_CLIPS_PER_WORD = 20


class ClipRecorder:
    def __init__(self):
        self.recording = False
        self.clips = []  # List of (frames, label)
        self.current_frames = []
        self.start_time = None

    def start_recording(self):
        self.recording = True
        self.current_frames = []
        self.start_time = time.time()

    def stop_recording(self):
        self.recording = False
        duration = time.time() - self.start_time if self.start_time else 0
        return len(self.current_frames), duration

    def add_frame(self, frame_data):
        if self.recording:
            self.current_frames.append(frame_data)

    def get_current_clip(self):
        return self.current_frames

    def save_clip(self, label, clip_id, output_dir):
        if not self.current_frames:
            return False

        clip = {
            "label": label,
            "clip_id": clip_id,
            "num_frames": len(self.current_frames),
            "fps_sampled": 15,  # We sample every 2nd frame from ~30fps camera
            "frames": self.current_frames,
            "timestamp": time.time(),
        }

        # Save individual clip
        clip_path = output_dir / f"{label}_{clip_id:03d}.json"
        with open(clip_path, "w") as f:
            json.dump(clip, f, indent=2)

        self.clips.append(clip)
        return True


def extract_frame_landmarks(hand_results, face_results):
    """Extract landmarks from a single frame into a serializable dict."""
    frame = {"hands": [], "face": None}

    if hand_results.multi_hand_landmarks:
        for hand_lms in hand_results.multi_hand_landmarks:
            hand_data = [
                {"x": lm.x, "y": lm.y, "z": lm.z}
                for lm in hand_lms.landmark
            ]
            frame["hands"].append(hand_data)

    if face_results.multi_face_landmarks:
        face_lms = face_results.multi_face_landmarks[0]
        frame["face"] = [
            {"x": lm.x, "y": lm.y, "z": lm.z}
            for lm in face_lms.landmark[:468]
        ]

    return frame


def count_existing_clips(output_dir, label):
    """Count how many clips already exist for a label."""
    return len(list(output_dir.glob(f"{label}_*.json")))


def draw_status(frame, recorder, label, clip_count, target_count, mode="idle"):
    """Draw recording status overlay on frame."""
    h, w = frame.shape[:2]

    # Background bar
    cv2.rectangle(frame, (0, 0), (w, 60), (0, 0, 0), -1)

    if mode == "recording":
        # Red recording indicator
        cv2.circle(frame, (30, 30), 12, (0, 0, 255), -1)
        cv2.putText(frame, f"REC - {label}", (55, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        frame_count = len(recorder.current_frames)
        cv2.putText(frame, f"Frames: {frame_count}", (w - 200, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    elif mode == "review":
        cv2.putText(frame, f"Clip grabado: {len(recorder.current_frames)} frames",
                    (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(frame, "ENTER=Guardar  ESC=Descartar", (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    else:
        progress = f"{clip_count}/{target_count}"
        cv2.putText(frame, f"Palabra: {label}  ({progress})",
                    (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(frame, "SPACE=Grabar  q=Salir", (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)


def capture_clips(output_dir, words, target_per_word):
    """Main capture loop."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: No se pudo abrir la cámara")
        sys.exit(1)

    # Set camera resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    mp_hands = mp.solutions.hands
    mp_face = mp.solutions.face_mesh

    recorder = ClipRecorder()
    current_word_idx = 0
    mode = "idle"  # idle, recording, review
    frame_counter = 0

    print("\n" + "=" * 60)
    print("CAPTURA DE SEÑAS DINÁMICAS - SeñasCL")
    print("=" * 60)
    print(f"Palabras: {', '.join(words)}")
    print(f"Objetivo: {target_per_word} clips por palabra")
    print(f"Controles: SPACE=grabar, ENTER=guardar, ESC=descartar, q=salir")
    print("=" * 60 + "\n")

    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as hands, mp_face.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        min_detection_confidence=0.5,
    ) as face_mesh:

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Mirror frame for natural interaction
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)
            face_results = face_mesh.process(rgb)

            # Draw hand landmarks on frame
            if results.multi_hand_landmarks:
                for hand_lms in results.multi_hand_landmarks:
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame, hand_lms, mp_hands.HAND_CONNECTIONS
                    )

            # Process current word
            if current_word_idx < len(words):
                label = words[current_word_idx]
                clip_count = count_existing_clips(output_dir, label)

                if clip_count >= target_per_word:
                    # Word complete, move to next
                    print(f"  [✓] {label}: {clip_count} clips completos")
                    current_word_idx += 1
                    continue

                # Extract landmarks if recording
                if mode == "recording":
                    frame_data = extract_frame_landmarks(results, face_results)
                    if frame_data["hands"]:  # Only add if hands detected
                        recorder.add_frame(frame_data)
                        frame_counter += 1

                        # Auto-cut at max frames
                        if frame_counter >= MAX_FRAMES:
                            print(f"  [!] Corte automático en {MAX_FRAMES} frames")
                            _, duration = recorder.stop_recording()
                            print(f"  Duración: {duration:.1f}s, Frames: {frame_counter}")
                            mode = "review"

                # Draw status
                draw_status(frame, recorder, label, clip_count, target_per_word, mode)

            else:
                cv2.putText(frame, "TODAS LAS PALABRAS COMPLETAS", (20, 38),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(frame, "Presiona q para salir", (20, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            cv2.imshow("SeñasCL - Captura de Señas Dinámicas", frame)

            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                break

            elif key == ord(' ') and current_word_idx < len(words):
                if mode == "idle":
                    mode = "recording"
                    recorder.start_recording()
                    frame_counter = 0
                    print(f"  [●] Grabando {label}...", end="", flush=True)
                elif mode == "recording":
                    _, duration = recorder.stop_recording()
                    print(f" ({duration:.1f}s, {frame_counter} frames)")
                    mode = "review"

            elif key == 13 and mode == "review":  # ENTER
                label = words[current_word_idx]
                clip_count = count_existing_clips(output_dir, label)
                success = recorder.save_clip(label, clip_count, output_dir)
                if success:
                    print(f"  [✓] Guardado: {label}_{clip_count:03d}.json")
                recorder.current_frames = []
                mode = "idle"

            elif key == 27 and mode == "review":  # ESC
                print(f"  [✗] Clip descartado")
                recorder.current_frames = []
                mode = "idle"

            elif key == 27 and mode == "idle":  # ESC
                break

    cap.release()
    cv2.destroyAllWindows()

    # Print summary
    print("\n" + "=" * 60)
    print("RESUMEN DE CAPTURA")
    print("=" * 60)
    for word in words:
        count = count_existing_clips(output_dir, word)
        status = "✓" if count >= target_per_word else "!"
        print(f"  {status} {word}: {count}/{target_per_word} clips")
    print(f"\nTotal clips: {len(list(output_dir.glob('*.json')))}")
    print(f"Directorio: {output_dir}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Captura clips de señas dinámicas para entrenamiento"
    )
    parser.add_argument(
        "--output-dir",
        default="ml/datasets/clips",
        help="Directorio donde guardar los clips (default: ml/datasets/clips/)"
    )
    parser.add_argument(
        "--words",
        nargs="+",
        default=DEFAULT_WORDS,
        help="Palabras a grabar (default: palabras del MVP)"
    )
    parser.add_argument(
        "--target",
        type=int,
        default=TARGET_CLIPS_PER_WORD,
        help=f"Clips objetivo por palabra (default: {TARGET_CLIPS_PER_WORD})"
    )
    args = parser.parse_args()

    capture_clips(args.output_dir, args.words, args.target)


if __name__ == "__main__":
    main()
