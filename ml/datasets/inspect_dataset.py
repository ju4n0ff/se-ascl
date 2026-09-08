"""
SeñasCL - Dataset Inspector
Verifies clip dataset balance and quality for temporal model training.

Usage:
    python inspect_dataset.py --dataset-dir ml/datasets/clips/
    python inspect_dataset.py --dataset-dir ml/datasets/clips/ --verbose

Reports:
    - Total clips per word
    - Frame count statistics (min/max/mean/median) per word
    - Balance warnings if any word has significantly fewer clips
    - Overall dataset quality assessment
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict
import statistics


def load_clip(clip_path):
    """Load a single clip file and return basic info."""
    try:
        with open(clip_path) as f:
            clip = json.load(f)
        return {
            "path": str(clip_path),
            "label": clip.get("label", "unknown"),
            "num_frames": clip.get("num_frames", 0),
            "has_hands": any(f.get("hands") for f in clip.get("frames", [])),
            "has_face": any(f.get("face") for f in clip.get("frames", [])),
        }
    except (json.JSONDecodeError, KeyError) as e:
        return None


def inspect_dataset(dataset_dir, verbose=False):
    """Inspect the dataset and print a report."""
    dataset_dir = Path(dataset_dir)

    if not dataset_dir.exists():
        print(f"Error: Directorio no encontrado: {dataset_dir}")
        sys.exit(1)

    clip_files = list(dataset_dir.glob("*.json"))
    if not clip_files:
        print(f"Error: No se encontraron clips en {dataset_dir}")
        sys.exit(1)

    # Group clips by label
    clips_by_label = defaultdict(list)
    errors = []

    for clip_path in clip_files:
        clip_info = load_clip(clip_path)
        if clip_info:
            clips_by_label[clip_info["label"]].append(clip_info)
        else:
            errors.append(str(clip_path))

    # Print header
    print("\n" + "=" * 70)
    print("INSPECCIÓN DE DATASET - SeñasCL")
    print("=" * 70)
    print(f"Directorio: {dataset_dir}")
    print(f"Total archivos: {len(clip_files)}")
    print(f"Clips válidos: {len(clip_files) - len(errors)}")
    if errors:
        print(f"Archivos con error: {len(errors)}")
        if verbose:
            for e in errors:
                print(f"  - {e}")
    print("=" * 70)

    if not clips_by_label:
        print("No hay clips válidos para analizar.")
        sys.exit(1)

    # Calculate statistics per word
    word_stats = {}
    for label, clips in sorted(clips_by_label.items()):
        frame_counts = [c["num_frames"] for c in clips]
        hands_count = sum(1 for c in clips if c["has_hands"])
        face_count = sum(1 for c in clips if c["has_face"])

        stats = {
            "count": len(clips),
            "frames_min": min(frame_counts) if frame_counts else 0,
            "frames_max": max(frame_counts) if frame_counts else 0,
            "frames_mean": statistics.mean(frame_counts) if frame_counts else 0,
            "frames_median": statistics.median(frame_counts) if frame_counts else 0,
            "frames_stdev": statistics.stdev(frame_counts) if len(frame_counts) > 1 else 0,
            "with_hands": hands_count,
            "with_face": face_count,
        }
        word_stats[label] = stats

    # Print word statistics
    print(f"\n{'PALABRA':<15} {'CLIPS':>6} {'FRAMES':>20} {'CON MANOS':>10} {'CON CARA':>10}")
    print("-" * 70)

    total_clips = 0
    total_frames_all = []
    clip_counts = []

    for label, stats in sorted(word_stats.items()):
        total_clips += stats["count"]
        total_frames_all.extend([stats["frames_mean"]] * stats["count"])
        clip_counts.append(stats["count"])

        frames_str = f"{stats['frames_min']}-{stats['frames_max']} (μ={stats['frames_mean']:.0f})"
        print(
            f"{label:<15} {stats['count']:>6} {frames_str:>20} "
            f"{stats['with_hands']:>10} {stats['with_face']:>10}"
        )

    print("-" * 70)
    print(f"{'TOTAL':<15} {total_clips:>6}")

    # Balance analysis
    print("\n" + "=" * 70)
    print("ANÁLISIS DE BALANCE")
    print("=" * 70)

    if clip_counts:
        mean_count = statistics.mean(clip_counts)
        stdev_count = statistics.stdev(clip_counts) if len(clip_counts) > 1 else 0
        min_count = min(clip_counts)
        max_count = max(clip_counts)

        print(f"Promedio clips/palabra: {mean_count:.1f}")
        print(f"Desviación estándar: {stdev_count:.1f}")
        print(f"Mínimo: {min_count}, Máximo: {max_count}")

        # Check for imbalance
        imbalance_threshold = mean_count * 0.5  # Warn if < 50% of mean
        underrepresented = [
            label for label, stats in word_stats.items()
            if stats["count"] < imbalance_threshold
        ]

        if underrepresented:
            print(f"\n⚠ PALABRAS CON POCOS CLIPS (< {imbalance_threshold:.0f}):")
            for label in underrepresented:
                print(f"  - {label}: {word_stats[label]['count']} clips")
        else:
            print("\n✓ Dataset balanceado razonablemente")

    # Frame count analysis
    print("\n" + "=" * 70)
    print("ANÁLISIS DE DURACIÓN DE CLIPS")
    print("=" * 70)

    all_frame_counts = []
    for clips in clips_by_label.values():
        all_frame_counts.extend([c["num_frames"] for c in clips])

    if all_frame_counts:
        # Assume ~15fps sampled (every 2nd frame from 30fps camera)
        fps_sampled = 15
        duration_ms = [f / fps_sampled * 1000 for f in all_frame_counts]

        print(f"Frames por clip: {min(all_frame_counts)}-{max(all_frame_counts)} "
              f"(μ={statistics.mean(all_frame_counts):.0f})")
        print(f"Duración estimada: {min(duration_ms):.0f}ms-{max(duration_ms):.0f}ms "
              f"(μ={statistics.mean(duration_ms):.0f}ms)")

        # Check for too-short clips
        short_clips = sum(1 for d in duration_ms if d < 500)
        if short_clips:
            print(f"\n⚠ {short_clips} clips duran menos de 500ms (pueden ser demasiado cortos)")

        # Check for too-long clips
        long_clips = sum(1 for d in duration_ms if d > 2500)
        if long_clips:
            print(f"⚠ {long_clips} clips duran más de 2500ms (pueden incluir silencios)")

    # Quality assessment
    print("\n" + "=" * 70)
    print("EVALUACIÓN DE CALIDAD")
    print("=" * 70)

    issues = []

    if len(word_stats) < 8:
        issues.append(f"Pocas palabras: {len(word_stats)} (mínimo recomendado: 8)")

    min_clips = min(clip_counts) if clip_counts else 0
    if min_clips < 15:
        issues.append(f"Algunas palabras tienen menos de 15 clips (mínimo: {min_clips})")

    if all_frame_counts and statistics.mean(all_frame_counts) < 10:
        issues.append("Promedio de frames muy bajo (< 10). Los clips pueden ser muy cortos.")

    if issues:
        print("PROBLEMAS ENCONTRADOS:")
        for issue in issues:
            print(f"  ⚠ {issue}")
    else:
        print("✓ Dataset listo para entrenamiento")

    print("\n" + "=" * 70)

    # Verbose mode: print per-clip details
    if verbose:
        print("\nDETALLE POR CLIP:")
        print("-" * 70)
        for label in sorted(clips_by_label.keys()):
            clips = clips_by_label[label]
            print(f"\n{label}:")
            for clip in sorted(clips, key=lambda c: c["path"]):
                frames = clip["num_frames"]
                hands = "✓" if clip["has_hands"] else "✗"
                face = "✓" if clip["has_face"] else "✗"
                print(f"  {Path(clip['path']).name:<30} {frames:>4} frames  "
                      f"manos={hands} cara={face}")


def main():
    parser = argparse.ArgumentParser(
        description="Inspect dynamic sign dataset for quality and balance"
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="Path to clips directory"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-clip details"
    )
    args = parser.parse_args()

    inspect_dataset(args.dataset_dir, args.verbose)


if __name__ == "__main__":
    main()
