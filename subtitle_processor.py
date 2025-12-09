"""
Subtitle Integration Module
Handles soft embedding and hard burning of subtitles
"""
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict

from config import SUBTITLE_CONFIG, DIRS, FFMPEG_CONFIG
from logger import logger, SubtitleError


class SubtitleProcessor:
    """Processes and embeds subtitles into video files"""
    
    def __init__(self):
        self.soft_subtitle = SUBTITLE_CONFIG['soft_subtitle']
        self.subtitle_codec = SUBTITLE_CONFIG['subtitle_codec']
        self.burn_style = SUBTITLE_CONFIG['burn_style']
    
    def get_video_info(self, video_path: Path) -> Dict:
        """
        Get video metadata using ffprobe
        
        Args:
            video_path: Path to video file
            
        Returns:
            Dictionary with video information
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(video_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            info = json.loads(result.stdout)
            
            # Extract relevant information
            video_stream = next(
                (s for s in info['streams'] if s['codec_type'] == 'video'),
                None
            )
            
            if not video_stream:
                raise SubtitleError("No video stream found")
            
            return {
                'width': int(video_stream.get('width', 0)),
                'height': int(video_stream.get('height', 0)),
                'duration': float(info['format'].get('duration', 0)),
                'bit_rate': int(info['format'].get('bit_rate', 0)),
                'codec': video_stream.get('codec_name', 'unknown'),
                'fps': eval(video_stream.get('r_frame_rate', '0/1'))
            }
            
        except subprocess.CalledProcessError as e:
            raise SubtitleError(f"Failed to get video info: {e.stderr}")
        except Exception as e:
            raise SubtitleError(f"Error reading video metadata: {e}")
    
    def validate_subtitle_file(self, subtitle_path: Path) -> bool:
        """
        Validate subtitle file format
        
        Args:
            subtitle_path: Path to subtitle file
            
        Returns:
            True if valid
        """
        if not subtitle_path.exists():
            raise SubtitleError(f"Subtitle file not found: {subtitle_path}")
        
        # Check if file is readable and not empty
        if subtitle_path.stat().st_size == 0:
            raise SubtitleError(f"Subtitle file is empty: {subtitle_path}")
        
        logger.info(f"Subtitle file validated: {subtitle_path}")
        return True
    
    def embed_soft_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Embed subtitle as a soft subtitle track (not burned in)
        
        Args:
            video_path: Path to input video
            subtitle_path: Path to subtitle file
            output_path: Optional output path
            
        Returns:
            Path to output video with embedded subtitles
        """
        logger.info("Embedding soft subtitles...")
        
        self.validate_subtitle_file(subtitle_path)
        
        if not output_path:
            output_path = DIRS['processing'] / f"{video_path.stem}_subtitled.mp4"
        
        try:
            # FFmpeg command for soft subtitle embedding
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-i', str(subtitle_path),
                '-c:v', 'copy',  # Copy video stream (no re-encoding)
                '-c:a', 'copy',  # Copy audio stream
                '-c:s', self.subtitle_codec,  # Subtitle codec
                '-metadata:s:s:0', 'language=eng',  # Set subtitle language
                '-metadata:s:s:0', 'title=English',  # Set subtitle title
                '-disposition:s:0', 'default',  # Make subtitle default
                '-y',  # Overwrite output
                str(output_path)
            ]
            
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            if output_path.exists():
                logger.info(f"Soft subtitles embedded successfully: {output_path}")
                return output_path
            else:
                raise SubtitleError("Output file was not created")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise SubtitleError(f"Failed to embed soft subtitles: {e.stderr}")
    
    def embed_hard_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Burn subtitle permanently into video frames (hard subtitle)
        
        Args:
            video_path: Path to input video
            subtitle_path: Path to subtitle file
            output_path: Optional output path
            
        Returns:
            Path to output video with burned subtitles
        """
        logger.info("Burning hard subtitles into video...")
        
        self.validate_subtitle_file(subtitle_path)
        
        if not output_path:
            output_path = DIRS['processing'] / f"{video_path.stem}_hardsubbed.mp4"
        
        # Import here to avoid circular dependency
        from config import PROCESSING_CONFIG
        low_memory = PROCESSING_CONFIG.get('low_memory_mode', False)
        
        try:
            # Escape subtitle path for FFmpeg filter
            # Windows paths need special handling
            subtitle_filter_path = str(subtitle_path).replace('\\', '/').replace(':', '\\\\:')
            
            # Memory-optimized settings for cloud environments
            if low_memory:
                logger.info("Using low-memory optimization for cloud environment")
                preset = 'veryfast'  # Faster, less memory
                crf = 28  # Higher CRF = lower quality but much less memory
                threads = 2  # Limit threads to reduce memory
            else:
                preset = FFMPEG_CONFIG['preset']
                crf = FFMPEG_CONFIG['crf']
                threads = 0  # Auto
            
            # FFmpeg command for hard subtitle burning
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-vf', f"subtitles='{subtitle_filter_path}':force_style='FontSize=20'",  # Smaller font reduces memory
                '-c:v', FFMPEG_CONFIG['video_codec'],
                '-crf', str(crf),
                '-preset', preset,
                '-threads', str(threads),
                '-c:a', 'copy',  # Copy audio stream
                '-max_muxing_queue_size', '1024',  # Prevent memory overflow
                '-y',  # Overwrite output
                str(output_path)
            ]
            
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            logger.info("This may take several minutes depending on video length...")
            
            # Run with progress output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True
            )
            
            # Monitor progress
            for line in process.stdout:
                if 'time=' in line:
                    # Extract and log progress
                    logger.debug(line.strip())
            
            process.wait()
            
            if process.returncode != 0:
                error_msg = f"FFmpeg process failed with code {process.returncode}"
                
                # Specific error messages for common Railway issues
                if process.returncode == -9:
                    error_msg += " (Process killed - likely out of memory. Try using soft subtitles or upgrade Railway plan)"
                elif process.returncode == 137:
                    error_msg += " (Out of memory error. Railway free tier has 512MB limit)"
                elif process.returncode == 1:
                    error_msg += " (Encoding error - check video format and subtitle file)"
                
                logger.error(error_msg)
                raise SubtitleError(error_msg)
            
            if output_path.exists():
                file_size = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"Hard subtitles burned successfully: {output_path} ({file_size:.2f} MB)")
                return output_path
            else:
                raise SubtitleError("Output file was not created")
                
        except subprocess.CalledProcessError as e:
            raise SubtitleError(f"Failed to burn hard subtitles: {e}")
        except Exception as e:
            error_str = str(e)
            if 'killed' in error_str.lower() or 'code -9' in error_str:
                raise SubtitleError(f"Process killed by system (out of memory). Use soft subtitles instead or upgrade server. Original error: {e}")
            raise SubtitleError(f"Unexpected error during subtitle burning: {e}")
    
    def process_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        use_soft_subtitle: Optional[bool] = None
    ) -> Path:
        """
        Process subtitle based on configuration (soft or hard)
        
        Args:
            video_path: Path to video file
            subtitle_path: Path to subtitle file
            use_soft_subtitle: Override config setting
            
        Returns:
            Path to processed video
        """
        soft_sub = use_soft_subtitle if use_soft_subtitle is not None else self.soft_subtitle
        
        logger.info(f"Processing {'soft' if soft_sub else 'hard'} subtitles...")
        
        # Get video info
        video_info = self.get_video_info(video_path)
        logger.info(
            f"Video info: {video_info['width']}x{video_info['height']}, "
            f"{video_info['duration']:.2f}s, {video_info['codec']}"
        )
        
        if soft_sub:
            return self.embed_soft_subtitle(video_path, subtitle_path)
        else:
            return self.embed_hard_subtitle(video_path, subtitle_path)


if __name__ == '__main__':
    # Test subtitle processor
    processor = SubtitleProcessor()
    print(f"Subtitle mode: {'Soft' if processor.soft_subtitle else 'Hard'}")
    print("Subtitle processor initialized successfully!")
