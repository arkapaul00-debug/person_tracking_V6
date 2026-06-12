import subprocess
import os
import math
import logging

logger = logging.getLogger(__name__)

def get_video_duration(input_path):
    """Returns the duration of the video in seconds."""
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        input_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Failed to get video duration: {e}")
        return 0.0

def split_video(input_path, output_dir, chunk_duration_sec=900):
    """
    Splits a video into chunks of specified duration using ffmpeg stream copy (fast/lossless).
    Default chunk size: 15 minutes (900 seconds).
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    duration = get_video_duration(input_path)
    if duration == 0:
        raise ValueError("Could not determine video duration.")
    
    num_chunks = math.ceil(duration / chunk_duration_sec)
    chunk_paths = []
    
    logger.info(f"Splitting {input_path} ({duration:.2f}s) into {num_chunks} chunks of {chunk_duration_sec}s...")
    
    for i in range(num_chunks):
        start_time = i * chunk_duration_sec
        chunk_filename = f"chunk_{i:03d}.mp4"
        chunk_path = os.path.join(output_dir, chunk_filename)
        
        # FFmpeg command for stream copy split
        # -ss before -i is faster seeking
        cmd = [
            'ffmpeg',
            '-ss', str(start_time),
            '-t', str(chunk_duration_sec),
            '-i', input_path,
            '-c', 'copy', # Stream copy (very fast, no re-encoding)
            '-y', # Overwrite correct
            chunk_path
        ]
        
        try:
            # Add timeout to prevent hangs (chunk duration + buffer)
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=chunk_duration_sec + 60)
            chunk_paths.append(chunk_path)
            logger.info(f"Created chunk {i+1}/{num_chunks}: {chunk_path}")
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout splitting chunk {i}")
            raise RuntimeError(f"Timeout splitting chunk {i}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error splitting chunk {i}: {e}")
            # Try to continue or raise? For now, we raise to stop bad pipeline.
            raise e
            
    return chunk_paths

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python video_splitter.py <input_video> <output_dir> [chunk_sec]")
    else:
        vid = sys.argv[1]
        out = sys.argv[2]
        sec = int(sys.argv[3]) if len(sys.argv) > 3 else 900
        split_video(vid, out, sec)
