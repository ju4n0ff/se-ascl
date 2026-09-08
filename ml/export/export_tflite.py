"""
SeñasCL - Model Export Script
Converts trained model to TFLite with INT8 quantization.

Usage:
    python export_tflite.py --model model.h5 --output model.tflite

Requires:
    pip install tensorflow
"""

import argparse
import sys

try:
    pass  # tensorflow import when needed
except ImportError:
    print("Install: pip install tensorflow")
    sys.exit(1)


def convert_to_tflite(model_path: str, output_path: str, quantize: bool = True):
    # TODO: Implement actual conversion
    # Steps:
    # 1. Load trained model (Keras/TF)
    # 2. Convert with TFLiteConverter
    # 3. Apply INT8 quantization if requested
    # 4. Save .tflite file
    print(f"Input: {model_path}")
    print(f"Output: {output_path}")
    print(f"Quantize: {quantize}")
    print("TODO: Implement TFLite conversion")


def main():
    parser = argparse.ArgumentParser(description="Export model to TFLite")
    parser.add_argument("--model", required=True, help="Path to trained model")
    parser.add_argument("--output", default="model.tflite", help="Output .tflite path")
    parser.add_argument("--quantize", action="store_true", default=True, help="INT8 quantization")
    args = parser.parse_args()

    convert_to_tflite(args.model, args.output, args.quantize)


if __name__ == "__main__":
    main()
