"""
Video Encoding Module
Handles multi-resolution video transcoding
"""
import subprocess
import json
import math
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import RESOLUTIONS, FFMPEG_CONFIG, DIRS, PROCESSING_CONFIG, get_output_filename
from logger import logger, EncodingError


class VideoEncoder:
    """Handles video encoding to multiple resolutions"""
    
    def __init__(self):
        self.resolutions = RESOLUTIONS
        self.video_codec = FFMPEG_CONFIG['video_codec']
        self.audio_codec = FFMPEG_CONFIG['audio_codec']
        self.preset = FFMPEG_CONFIG['preset']
        self.crf = FFMPEG_CONFIG['crf']
        self.pixel_format = FFMPEG_CONFIG['pixel_format']
    
    def calculate_output_width(self, original_width: int, original_height: int, target_height: int) -> int:
        """
        Calculate output width maintaining aspect ratio
        
        Args:
            original_width: Original video width
            original_height: Original video height
            target_height: Target output height
            
        Returns:
            Calculated width (even number for codec compatibility)
        """
        aspect_ratio = original_width / original_height
        calculated_width = int(target_height * aspect_ratio)
        
        # Ensure width is even (required by many codecs)
        if calculated_width % 2 != 0:
            calculated_width += 1
        
        return calculated_width
    
    def get_video_dimensions(self, video_path: Path) -> tuple:
        """
        Get video dimensions using ffprobe
        
        Args:
            video_path: Path to video file
            
        Returns:
            Tuple of (width, height)
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'json',
                str(video_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            info = json.loads(result.stdout)
            stream = info['streams'][0]
            
            return int(stream['width']), int(stream['height'])
            
        except Exception as e:
            raise EncodingError(f"Failed to get video dimensions: {e}")
    
    def encode_resolution(
        self,
        input_video: Path,
        resolution_name: str,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Encode video to specific resolution
        
        Args:
            input_video: Path to input video
            resolution_name: Resolution key (e.g., '720p')
            output_dir: Optional output directory
            
        Returns:
            Path to encoded video
        """
        if resolution_name not in self.resolutions:
            raise EncodingError(f"Unknown resolution: {resolution_name}")
        
        config = self.resolutions[resolution_name]
        target_height = config['height']
        
        # Get original dimensions
        original_width, original_height = self.get_video_dimensions(input_video)
        
        # Calculate output dimensions
        output_width = self.calculate_output_width(original_width, original_height, target_height)
        
        # Set output directory
        if not output_dir:
            output_dir = DIRS['outputs'] / resolution_name
            output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate output filename
        output_filename = get_output_filename(input_video.name, resolution_name, with_subtitles=True)
        output_path = output_dir / output_filename
        
        logger.info(f"Encoding {resolution_name}: {output_width}x{target_height}")
        logger.info(f"Output: {output_path}")
        
        # Check for low-memory mode
        from config import PROCESSING_CONFIG
        low_memory = PROCESSING_CONFIG.get('low_memory_mode', False)
        
        try:
            # Build FFmpeg command with memory optimizations
            if low_memory:
                logger.info("Using low-memory optimization for encoding")
                thread_count = 2
                preset = 'veryfast'
            else:
                thread_count = FFMPEG_CONFIG['max_threads']
                preset = config.get('preset', self.preset)
            
            cmd = [
                'ffmpeg',
                '-i', str(input_video),
                '-vf', f'scale={output_width}:{target_height}',
                '-c:v', self.video_codec,
                '-preset', preset,
                '-crf', str(self.crf),
                '-b:v', config['bitrate_video'],
                '-maxrate', config['bitrate_video'],
                '-bufsize', str(int(config['bitrate_video'].replace('k', '')) * 2) + 'k',
                '-c:a', self.audio_codec,
                '-b:a', config['bitrate_audio'],
                '-ac', '2',  # Stereo audio
                '-pix_fmt', self.pixel_format,
                '-movflags', '+faststart',  # Enable streaming
                '-threads', str(thread_count),
                '-max_muxing_queue_size', '1024',  # Prevent memory overflow
                '-y',  # Overwrite output
                str(output_path)
            ]
            
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            logger.info(f"Starting {resolution_name} encoding (this may take several minutes)...")
            
            # Run FFmpeg with progress monitoring
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True
            )
            
            # Monitor encoding progress
            for line in process.stdout:
                if 'time=' in line and 'speed=' in line:
                    # Log progress periodically
                    logger.debug(line.strip())
            
            process.wait()
            
            if process.returncode != 0:
                raise EncodingError(f"FFmpeg encoding failed with code {process.returncode}")
            
            if not output_path.exists():
                raise EncodingError(f"Output file was not created: {output_path}")
            
            # Get output file size
            output_size = output_path.stat().st_size / (1024 * 1024)  # MB
            logger.info(f"✓ {resolution_name} encoding completed: {output_size:.2f} MB")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            raise EncodingError(f"Failed to encode {resolution_name}: {e}")
        except Exception as e:
            raise EncodingError(f"Unexpected error during {resolution_name} encoding: {e}")
    
    def encode_all_resolutions(
        self,
        input_video: Path,
        resolutions: Optional[List[str]] = None,
        parallel: bool = None
    ) -> Dict[str, Path]:
        """
        Encode video to all specified resolutions
        
        Args:
            input_video: Path to input video
            resolutions: List of resolution names (default: all)
            parallel: Enable parallel encoding (default: from config)
            
        Returns:
            Dictionary mapping resolution names to output paths
        """
        if resolutions is None:
            resolutions = list(self.resolutions.keys())
        
        if parallel is None:
            parallel = PROCESSING_CONFIG['parallel_encoding']
        
        logger.info(f"Starting multi-resolution encoding for: {resolutions}")
        logger.info(f"Parallel encoding: {'Enabled' if parallel else 'Disabled'}")
        
        output_files = {}
        
        if parallel:
            # Parallel encoding using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(resolutions)) as executor:
                future_to_resolution = {
                    executor.submit(self.encode_resolution, input_video, res): res
                    for res in resolutions
                }
                
                for future in as_completed(future_to_resolution):
                    resolution = future_to_resolution[future]
                    try:
                        output_path = future.result()
                        output_files[resolution] = output_path
                    except Exception as e:
                        logger.error(f"Failed to encode {resolution}: {e}")
                        # Continue with other resolutions
        else:
            # Sequential encoding
            for resolution in resolutions:
                try:
                    output_path = self.encode_resolution(input_video, resolution)
                    output_files[resolution] = output_path
                except Exception as e:
                    logger.error(f"Failed to encode {resolution}: {e}")
                    # Continue with other resolutions
        
        logger.info(f"Encoding completed for {len(output_files)}/{len(resolutions)} resolutions")
        return output_files
    
    def create_preview_thumbnails(self, video_path: Path, output_dir: Optional[Path] = None) -> List[Path]:
        """
        Generate preview thumbnails from video
        
        Args:
            video_path: Path to video file
            output_dir: Optional output directory for thumbnails
            
        Returns:
            List of paths to generated thumbnails
        """
        if not output_dir:
            output_dir = DIRS['outputs'] / 'thumbnails'
            output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Generating preview thumbnails...")
        
        try:
            # Generate thumbnails at 10%, 50%, and 90% of video duration
            timestamps = ['00:00:10', '00:01:00', '00:02:00']
            thumbnail_paths = []
            
            for i, timestamp in enumerate(timestamps, 1):
                thumbnail_path = output_dir / f"{video_path.stem}_thumb_{i}.jpg"
                
                cmd = [
                    'ffmpeg',
                    '-ss', timestamp,
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-q:v', '2',
                    '-y',
                    str(thumbnail_path)
                ]
                
                subprocess.run(cmd, capture_output=True, check=True)
                
                if thumbnail_path.exists():
                    thumbnail_paths.append(thumbnail_path)
                    logger.info(f"Thumbnail created: {thumbnail_path}")
            
            return thumbnail_paths
            
        except Exception as e:
            logger.warning(f"Failed to generate thumbnails: {e}")
            return []


if __name__ == '__main__':
    # Test encoder
    encoder = VideoEncoder()
    print(f"Video codec: {encoder.video_codec}")
    print(f"Available resolutions: {list(encoder.resolutions.keys())}")
    
    # Test dimension calculation
    width = encoder.calculate_output_width(1920, 1080, 720)
    print(f"Calculated width for 720p from 1920x1080: {width}")
