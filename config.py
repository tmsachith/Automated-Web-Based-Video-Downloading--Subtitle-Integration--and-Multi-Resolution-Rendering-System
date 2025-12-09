"""
Configuration Management for Automated Video Processing System
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent

# Directory structure
DIRS = {
    'downloads': BASE_DIR / 'downloads',
    'processing': BASE_DIR / 'processing',
    'outputs': BASE_DIR / 'outputs',
    'logs': BASE_DIR / 'logs',
    'temp': BASE_DIR / 'temp'
}

# Create directories if they don't exist
for dir_path in DIRS.values():
    dir_path.mkdir(parents=True, exist_ok=True)

# Resolution configurations
RESOLUTIONS = {
    '360p': {
        'height': 360,
        'bitrate_video': '500k',
        'bitrate_audio': '96k',
        'preset': 'medium'
    },
    '480p': {
        'height': 480,
        'bitrate_video': '1000k',
        'bitrate_audio': '128k',
        'preset': 'medium'
    },
    '720p': {
        'height': 720,
        'bitrate_video': '2500k',
        'bitrate_audio': '192k',
        'preset': 'medium'
    },
    '1080p': {
        'height': 1080,
        'bitrate_video': '5000k',
        'bitrate_audio': '192k',
        'preset': 'medium'
    }
}

# FFmpeg settings
FFMPEG_CONFIG = {
    'video_codec': 'libx264',
    'audio_codec': 'aac',
    'preset': 'medium',
    'crf': 23,  # Constant Rate Factor (18-28, lower = better quality)
    'pixel_format': 'yuv420p',
    'max_threads': 0  # Use all available threads
}

# Subtitle settings
SUBTITLE_CONFIG = {
    'soft_subtitle': True,  # True for soft embed, False for hard burn
    'subtitle_codec': 'mov_text',  # For MP4 containers
    'burn_style': {
        'font_size': 24,
        'font_name': 'Arial',
        'primary_color': '&HFFFFFF',  # White
        'outline_color': '&H000000',  # Black outline
        'bold': False
    }
}

# Download settings
DOWNLOAD_CONFIG = {
    'chunk_size': 8192,  # 8KB chunks
    'timeout': 30,  # seconds
    'max_retries': 3,
    'verify_ssl': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Supported file formats
SUPPORTED_FORMATS = {
    'video': ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm'],
    'subtitle': ['.srt', '.ass', '.vtt', '.sub', '.ssa']
}

# Logging configuration
LOG_CONFIG = {
    'log_file': DIRS['logs'] / 'processing.log',
    'max_log_size': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5,
    'log_level': 'INFO'
}

# Cloud/Railway environment detection
IS_CLOUD_ENV = os.getenv('RAILWAY_ENVIRONMENT') is not None or os.getenv('DYNO') is not None

# Processing settings
PROCESSING_CONFIG = {
    'cleanup_temp_files': True,
    'keep_original_files': False,  # Don't keep originals to save space (especially for cloud)
    'low_memory_mode': IS_CLOUD_ENV,  # Enable memory optimizations on cloud platforms
    'batch_processing': False,
    'parallel_encoding': False  # Encode multiple resolutions simultaneously
}

# Web interface settings
WEB_CONFIG = {
    'host': os.getenv('HOST', '0.0.0.0'),
    'port': int(os.getenv('PORT', 5000)),
    'debug': os.getenv('FLASK_ENV', 'production') != 'production',
    'max_upload_size': 5 * 1024 * 1024 * 1024,  # 5GB (for large video files)
    'allowed_hosts': ['localhost', '127.0.0.1']
}

# Cloud deployment options
CLOUD_OPTIONS = {
    'recommended_free_services': [
        'Google Colab (GPU support, temporary)',
        'Kaggle Notebooks (GPU support, limited hours)',
        'Railway (500 hours/month free)',
        'Render (750 hours/month free)',
        'Fly.io (Limited free tier)'
    ]
}

def get_output_filename(original_name: str, resolution: str, with_subtitles: bool = True) -> str:
    """
    Generate standardized output filename
    
    Args:
        original_name: Original video filename
        resolution: Target resolution (e.g., '720p')
        with_subtitles: Whether subtitles are embedded
        
    Returns:
        Formatted filename
    """
    base_name = Path(original_name).stem
    subtitle_tag = '_subtitled' if with_subtitles else ''
    return f"{base_name}_{resolution}{subtitle_tag}.mp4"

def validate_config():
    """Validate configuration and check for FFmpeg installation"""
    import shutil
    
    if not shutil.which('ffmpeg'):
        raise EnvironmentError(
            "FFmpeg not found in system PATH. "
            "Please install FFmpeg: https://ffmpeg.org/download.html"
        )
    
    if not shutil.which('ffprobe'):
        raise EnvironmentError(
            "FFprobe not found in system PATH. "
            "Please install FFmpeg with FFprobe included."
        )
    
    return True

if __name__ == '__main__':
    print("Configuration loaded successfully!")
    print(f"Base directory: {BASE_DIR}")
    print(f"Directories created: {list(DIRS.keys())}")
    try:
        validate_config()
        print("✓ FFmpeg is installed and accessible")
    except EnvironmentError as e:
        print(f"✗ Configuration error: {e}")
