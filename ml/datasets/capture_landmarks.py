"""
SeñasCL - Dataset Capture Script
Captura landmarks de manos/rostro desde video para entrenamiento.

Usage:
    python capture_landmarks.py --input video.mp4 --output dataset.json

Requires:
    pip install mediapipe opencv-python
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import mediapipe as mp
    import cv2
except ImportError:
    print("Install dependencies: pip install mediapipe opencv-python")
    sys.exit(1)

mp_hands = mp.solutions.hands
mp_face = mp.solutions.face_mesh
mp_pose = mp.solutions.pose


def extract_landmarks_from_video(video_path: str, label: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video {video_path}")
        return []

    samples = []
    frame_idx = 0

    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.5,
    ) as hands, mp_face.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        min_detection_confidence=0.5,
    ) as face_mesh:

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % 2 == 0:  # Sample every 2nd frame
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                hand_results = hands.process(rgb)
                face_results = face_mesh.process(rgb)

                sample = {
                    "frame": frame_idx,
                    "label": label,
                    "hands": [],
                    "face": None,
                }

                if hand_results.multi_hand_landmarks:
                    for hand_landmarks in hand_results.multi_hand_landmarks:
                        hand_data = [
                            {"x": lm.x, "y": lm.y, "z": lm.z}
                            for lm in hand_landmarks.landmark
                        ]
                        sample["hands"].append(hand_data)

                if face_results.multi_face_landmarks:
                    face_landmarks = face_results.multi_face_landmarks[0]
                    sample["face"] = [
                        {"x": lm.x, "y": lm.y, "z": lm.z}
                        for lm in face_landmarks.landmark[:468]
                    ]

                if sample["hands"]:
                    samples.append(sample)

            frame_idx += 1

    cap.release()
    return samples


def main():
    parser = argparse.ArgumentParser(description="Capture landmarks for LSCh training")
    parser.add_argument("--input", required=True, help="Path to video file or directory")
    parser.add_argument("--output", default="dataset.json", help="Output JSON path")
    parser.add_argument("--label", default="unknown", help="Sign label for this video")
    args = parser.parse_args()

    input_path = Path(args.input)
    all_samples = []

    if input_path.is_file():
        samples = extract_landmarks_from_video(str(input_path), args.label)
        all_samples.extend(samples)
    elif input_path.is_dir():
        for video_file in sorted(input_path.glob("*.mp4")):
            label = video_file.stem
            print(f"Processing {video_file.name} (label: {label})")
            samples = extract_landmarks_from_video(str(video_file), label)
            all_samples.extend(samples)
    else:
        print(f"Error: {input_path} not found")
        sys.exit(1)

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(all_samples, f, indent=2)

    print(f"Captured {len(all_samples)} samples to {output_path}")


if __name__ == "__main__":
    main()
