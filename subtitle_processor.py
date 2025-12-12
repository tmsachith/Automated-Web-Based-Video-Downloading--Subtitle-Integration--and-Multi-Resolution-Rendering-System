"""
Subtitle Integration Module
Handles soft embedding and hard burning of subtitles
"""
import subprocess
import json
import os
import time
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
    
    def find_sinhala_font(self) -> str:
        """
        Find available Sinhala font from project Fonts folder
        
        Returns:
            Path to font file
        """
        # Check project Fonts folder first (for deployment)
        project_fonts = DIRS.get('fonts', Path('Fonts'))
        if not isinstance(project_fonts, Path):
            project_fonts = Path('Fonts')
        
        # List of Sinhala fonts to try (in priority order)
        sinhala_fonts = [
            'NotoSansSinhala-Regular.ttf',
            'NotoSansSinhala.ttf',
            'NotoSansSinhala-Bold.ttf',
        ]
        
        # Check if fonts exist in project folder
        if project_fonts.exists():
            for font_file in sinhala_fonts:
                font_path = project_fonts / font_file
                if font_path.exists():
                    logger.info(f"Found Sinhala font in project: {font_path}")
                    return str(font_path.absolute())
        
        # Fallback: Check Windows fonts (for local development)
        windows_fonts = Path(r'C:\Windows\Fonts')
        if windows_fonts.exists():
            for font_file in sinhala_fonts:
                font_path = windows_fonts / font_file
                if font_path.exists():
                    logger.info(f"Found Sinhala font in Windows: {font_path}")
                    return str(font_path)
        
        # Last resort: use project font path even if not verified
        fallback_path = project_fonts / 'NotoSansSinhala-Regular.ttf'
        logger.warning(f"Font not verified, using fallback path: {fallback_path}")
        return str(fallback_path.absolute())
    
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
    
    def convert_srt_to_ass(self, srt_path: Path, ass_path: Path) -> bool:
        """Converts an SRT subtitle file to ASS format."""
        try:
            # The -y option overwrites the output file if it exists.
            command = [
                'ffmpeg',
                '-y', 
                '-i', str(srt_path),
                str(ass_path)
            ]
            logger.info(f"Converting SRT to ASS: {' '.join(command)}")
            # Using check=True will raise CalledProcessError on non-zero exit codes.
            process = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                check=True, 
                encoding='utf-8'
            )
            logger.info("Successfully converted SRT to ASS.")
            return True
        except subprocess.CalledProcessError as e:
            # Log the standard error from FFmpeg to diagnose the issue.
            logger.error(f"Error converting SRT to ASS. FFmpeg stderr:\n{e.stderr}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during SRT to ASS conversion: {e}")
            return False

    def validate_subtitle_file(self, subtitle_path: Path) -> bool:
        """
        Validates and cleans the subtitle file.
        Ensures the file is UTF-8 encoded.
        """
        if not subtitle_path.exists():
            logger.error(f"Subtitle file not found at {subtitle_path}")
            return False

        # --- Ensure UTF-8 encoding ---
        try:
            # Try to read as UTF-8. If it works, rewrite it to ensure it's clean.
            content = subtitle_path.read_text(encoding='utf-8')
            subtitle_path.write_text(content, encoding='utf-8')
            logger.info(f"Subtitle file {subtitle_path.name} is already UTF-8 or has been converted.")
        except UnicodeDecodeError:
            logger.warning(f"UTF-8 decoding failed for {subtitle_path.name}. Trying other encodings.")
            # If it fails, try to detect and convert from other common encodings.
            for encoding in ['utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    content = subtitle_path.read_text(encoding=encoding)
                    subtitle_path.write_text(content, encoding='utf-8')
                    logger.info(f"Successfully converted subtitle file from {encoding} to UTF-8.")
                    return True # Exit after successful conversion
                except (UnicodeDecodeError, IOError):
                    continue # Try the next encoding
            logger.error(f"Could not decode subtitle file {subtitle_path.name} with any of the attempted encodings.")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during subtitle validation: {e}")
            return False
            
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
            # FFmpeg command for soft subtitle embedding with UTF-8 support
            # -sub_charenc utf-8 ensures proper Unicode/Sinhala character handling
            cmd = [
                'ffmpeg',
                '-sub_charenc', 'utf-8',  # Force UTF-8 encoding for subtitles
                '-i', str(video_path),
                '-i', str(subtitle_path),
                '-c:v', 'copy',  # Copy video stream (no re-encoding)
                '-c:a', 'copy',  # Copy audio stream
                '-c:s', self.subtitle_codec,  # Subtitle codec
                '-metadata:s:s:0', 'language=sin',  # Set subtitle language to Sinhala
                '-metadata:s:s:0', 'title=Sinhala',  # Set subtitle title
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
        output_path: Optional[Path] = None,
        progress_callback=None,
        cancel_check=None
    ) -> Path:
        """
        Burn subtitle permanently into video frames (hard subtitle)
        WARNING: This is very slow (10-30 minutes) and CPU-intensive!
        This version converts SRT to ASS for better complex script rendering.
        
        Args:
            video_path: Path to input video
            subtitle_path: Path to subtitle file
            output_path: Optional output path
            progress_callback: Function(current_seconds, total_seconds) for progress
            cancel_check: Optional function() -> bool to check for cancellation
            
        Returns:
            Path to output video with burned subtitles
        """
        logger.info("Burning hard subtitles into video (ASS method)...")
        
        if not self.validate_subtitle_file(subtitle_path):
            raise SubtitleError("Subtitle file validation failed.")
        
        if not output_path:
            output_path = DIRS['processing'] / f"{video_path.stem}_hardsubbed.mp4"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Define paths for temporary files
        temp_dir = DIRS['temp']
        temp_dir.mkdir(exist_ok=True)
        ass_subtitle_path = temp_dir / f"{subtitle_path.stem}.ass"
        watermark_subtitle_path = temp_dir / "watermark.srt"

        # Convert main subtitle to ASS format for correct rendering
        if not self.convert_srt_to_ass(subtitle_path, ass_subtitle_path):
            raise SubtitleError("Failed to convert SRT to ASS.")

        # Create watermark subtitle file
        watermark_text = "1\\n00:00:00,000 --> 00:00:10,000\\nThis is MovieDownloadSL..."
        watermark_subtitle_path.write_text(watermark_text, encoding='utf-8')

        # Import here to avoid circular dependency
        from config import PROCESSING_CONFIG
        low_memory = PROCESSING_CONFIG.get('low_memory_mode', False)
        
        try:
            # Memory-optimized settings for cloud environments
            if low_memory:
                logger.info("Using low-memory optimization for cloud environment")
                preset = 'veryfast'
                crf = 28
                threads = 2
            else:
                preset = FFMPEG_CONFIG['preset']
                crf = FFMPEG_CONFIG['crf']
                threads = 0

            # FFmpeg command using two filters: one for watermark, one for main subtitles
            # The `ass` filter is used for the main subtitles for correct rendering.
            # The `subtitles` filter is used for the simple ASCII watermark.
            video_filters = [
                f"subtitles='{watermark_subtitle_path.as_posix()}':force_style='FontName=Arial,FontSize=16,PrimaryColour=&H80FFFFFF,Alignment=1'",
                f"ass='{ass_subtitle_path.as_posix()}'"
            ]
            
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', ",".join(video_filters),
                '-c:v', 'libx264',
                '-preset', preset,
                '-crf', str(crf),
                '-threads', str(threads),
                '-c:a', 'aac',
                '-b:a', '192k',
                str(output_path)
            ]

            logger.info(f"Running FFmpeg for hard subtitle embedding: {' '.join(cmd)}")
            
            # Get total duration for progress reporting
            video_info = self.get_video_info(video_path)
            total_duration = video_info.get('duration', 0)
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8')

            for line in process.stdout:
                logger.info(line.strip())
                if "time=" in line and progress_callback:
                    # Extract time and calculate progress
                    time_str = line.split('time=')[1].split(' ')[0]
                    h, m, s = map(float, time_str.split(':'))
                    current_seconds = h * 3600 + m * 60 + s
                    if total_duration > 0:
                        progress_callback(current_seconds, total_duration)

                if cancel_check and cancel_check():
                    logger.warning("Hard subtitle embedding cancelled by user.")
                    process.terminate()
                    time.sleep(0.5)
                    if process.poll() is None:
                        process.kill()
                    if output_path.exists():
                        output_path.unlink()
                    # Clean up temp files
                    if ass_subtitle_path.exists(): ass_subtitle_path.unlink()
                    if watermark_subtitle_path.exists(): watermark_subtitle_path.unlink()
                    raise SubtitleError("Hard subtitle embedding cancelled by user.")

            process.wait()

            # Clean up temporary files
            if ass_subtitle_path.exists():
                ass_subtitle_path.unlink()
            if watermark_subtitle_path.exists():
                watermark_subtitle_path.unlink()

            if process.returncode != 0:
                raise SubtitleError(f"FFmpeg process failed with code {process.returncode}")

            logger.info(f"Hard subtitle embedded successfully: {output_path}")
            return output_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise SubtitleError(f"Failed to burn hard subtitles: {e.stderr}")
        except Exception as e:
            # Clean up temp files on any exception
            if 'ass_subtitle_path' in locals() and ass_subtitle_path.exists():
                ass_subtitle_path.unlink()
            if 'watermark_subtitle_path' in locals() and watermark_subtitle_path.exists():
                watermark_subtitle_path.unlink()
            logger.error(f"An unexpected error occurred during hardsub burning: {e}")
            raise SubtitleError(f"An unexpected error occurred during hardsub burning: {e}")
    
    def process_subtitle(
        self,
        video_path: Path,
        subtitle_path: Path,
        use_soft_subtitle: Optional[bool] = None,
        progress_callback=None,
        cancel_check=None
    ) -> Path:
        """
        Process subtitle based on configuration (soft or hard)
        
        Args:
            video_path: Path to video file
            subtitle_path: Path to subtitle file
            use_soft_subtitle: Override config setting
            progress_callback: Function(current, total) for progress updates
            cancel_check: Optional function() -> bool to check for cancellation
            
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
            logger.info("✓ Soft subtitles are FAST (~1 minute)")
            return self.embed_soft_subtitle(video_path, subtitle_path)
        else:
            logger.warning("⚠️ Hard subtitles are VERY SLOW (10-30 minutes)!")
            logger.warning("💡 Consider using soft subtitles for production")
            return self.embed_hard_subtitle(video_path, subtitle_path, progress_callback=progress_callback, cancel_check=cancel_check)


if __name__ == '__main__':
    # Test subtitle processor
    processor = SubtitleProcessor()
    print(f"Subtitle mode: {'Soft' if processor.soft_subtitle else 'Hard'}")
    print("Subtitle processor initialized successfully!")
