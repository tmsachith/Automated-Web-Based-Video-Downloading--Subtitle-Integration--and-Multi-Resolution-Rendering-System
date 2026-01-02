"""
Subtitle Integration Module
Handles soft embedding and hard burning of subtitles
"""
import subprocess
import json
import os
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

    def _escape_ffmpeg_filter_path(self, path: Path) -> str:
        """Escape a filesystem path for use inside an FFmpeg filter argument.

        FFmpeg filter syntax treats ':' and '\\' specially on Windows paths.
        Using forward slashes + escaping ':' is the most reliable approach.
        """
        # Forward slashes for FFmpeg
        p = str(path.absolute()).replace('\\', '/')
        # Escape the drive letter colon (and any other colons)
        p = p.replace(':', r'\:')
        # Escape single quotes for FFmpeg filter single-quoted strings
        p = p.replace("'", r"\'")
        return p

    def _get_preferred_unicode_font_name(self) -> str:
        """Pick a font family name that supports Sinhala/Unicode."""
        project_fonts = DIRS.get('fonts', Path('Fonts'))
        if not isinstance(project_fonts, Path):
            project_fonts = Path('Fonts')

        # Prefer fonts we ship with the repo for predictable rendering
        if (project_fonts / 'NotoSansSinhala-Regular.ttf').exists() or (project_fonts / 'NotoSansSinhala.ttf').exists():
            return 'Noto Sans Sinhala'
        # Fall back to configured list
        for font_name in SUBTITLE_CONFIG.get('unicode_fonts', []):
            if font_name:
                return font_name

        return self.burn_style.get('font_name', 'DejaVu Sans')

    def ensure_ass_subtitle(self, subtitle_path: Path) -> Path:
        """Ensure a subtitle file is in ASS format for reliable hard-burn rendering.

        Sinhala (and many complex scripts) tend to render more consistently via ASS/libass,
        and converting avoids edge cases with SRT parsing/encoding.
        """
        suffix = subtitle_path.suffix.lower()
        if suffix in {'.ass', '.ssa'}:
            # Still ensure the ASS has the desired Sinhala font in its Default style
            try:
                self.inject_font_into_ass(subtitle_path)
            except Exception as e:
                logger.debug(f"ASS font injection skipped/failed: {e}")
            return subtitle_path

        # Normalize encoding first (so FFmpeg reads consistent UTF-8)
        self.validate_subtitle_file(subtitle_path)

        output_dir = DIRS.get('temp', Path('temp'))
        if not isinstance(output_dir, Path):
            output_dir = Path('temp')
        output_dir.mkdir(parents=True, exist_ok=True)

        ass_path = output_dir / f"{subtitle_path.stem}_converted.ass"

        logger.info(f"Converting subtitle to ASS for hard burn: {subtitle_path.name} -> {ass_path.name}")

        # FFmpeg can convert SRT/VTT/etc. into ASS directly.
        # Use -sub_charenc to force UTF-8 decoding for text-based inputs.
        cmd = [
            'ffmpeg',
            '-sub_charenc', 'UTF-8',
            '-i', str(subtitle_path),
            '-c:s', 'ass',
            '-y',
            str(ass_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg subtitle conversion stderr: {e.stderr}")
            raise SubtitleError(f"Failed to convert subtitle to ASS: {e.stderr}")

        if not ass_path.exists() or ass_path.stat().st_size == 0:
            raise SubtitleError("ASS subtitle conversion failed (output not created)")

        # Ensure the converted ASS explicitly uses a Sinhala-capable font in its style.
        self.inject_font_into_ass(ass_path)

        return ass_path

    def inject_font_into_ass(self, ass_path: Path, font_name: str = 'Noto Sans Sinhala') -> None:
        """Inject/update the Default ASS style to use a Sinhala-capable font.

        Note: ASS cannot truly embed a .ttf. This sets the style's Fontname field so libass
        can pick the right font if available at runtime.
        """
        if not ass_path.exists() or ass_path.stat().st_size == 0:
            raise SubtitleError(f"ASS file not found or empty: {ass_path}")

        content = ass_path.read_text(encoding='utf-8', errors='strict')
        if "[V4+ Styles]" not in content:
            raise SubtitleError("Invalid ASS subtitle file (missing [V4+ Styles])")

        lines = content.splitlines(True)  # keep line endings

        in_styles = False
        format_fields = None
        format_index = {}

        def normalize_field(name: str) -> str:
            return name.strip().lower()

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Enter/exit sections
            if stripped.startswith('[') and stripped.endswith(']'):
                in_styles = stripped.lower() == '[v4+ styles]'
                continue

            if not in_styles:
                continue

            # Parse format line
            if stripped.lower().startswith('format:'):
                format_fields = [f.strip() for f in stripped.split(':', 1)[1].split(',')]
                format_index = {normalize_field(name): idx for idx, name in enumerate(format_fields)}
                continue

            # Update Default style line
            if stripped.lower().startswith('style:') and format_fields and 'fontname' in format_index:
                style_payload = stripped.split(':', 1)[1].strip()
                parts = [p.strip() for p in style_payload.split(',')]

                # Defensive: ensure parts align with format
                if len(parts) < len(format_fields):
                    parts += [''] * (len(format_fields) - len(parts))

                name_idx = format_index.get('name', 0)
                font_idx = format_index['fontname']

                if parts[name_idx].strip().lower() == 'default':
                    parts[font_idx] = font_name

                    # Also apply basic style overrides when present
                    if 'fontsize' in format_index:
                        parts[format_index['fontsize']] = str(int(self.burn_style.get('font_size', 24)))
                    if 'primarycolour' in format_index:
                        parts[format_index['primarycolour']] = self.burn_style.get('primary_color', '&H00FFFFFF')
                    if 'outlinecolour' in format_index:
                        parts[format_index['outlinecolour']] = self.burn_style.get('outline_color', '&H00000000')
                    if 'bold' in format_index:
                        parts[format_index['bold']] = '1' if self.burn_style.get('bold', False) else '0'
                    if 'italic' in format_index:
                        parts[format_index['italic']] = '0'
                    if 'alignment' in format_index:
                        # Bottom-center is a sensible default (2)
                        parts[format_index['alignment']] = '2'
                    if 'marginl' in format_index:
                        parts[format_index['marginl']] = '20'
                    if 'marginr' in format_index:
                        parts[format_index['marginr']] = '20'
                    if 'marginv' in format_index:
                        parts[format_index['marginv']] = '30'

                    newline = '\n' if line.endswith('\n') else ''
                    updated = 'Style: ' + ','.join(parts) + newline
                    lines[i] = updated
                    break

        ass_path.write_text(''.join(lines), encoding='utf-8')
    
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
    
    def validate_subtitle_file(self, subtitle_path: Path) -> bool:
        """
        Validate subtitle file format and ensure UTF-8 encoding
        
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
        
        # Ensure subtitle file is UTF-8 encoded
        try:
            content = subtitle_path.read_text(encoding='utf-8')
            # If we can read it as UTF-8, re-write to ensure BOM-free UTF-8
            subtitle_path.write_text(content, encoding='utf-8')
            logger.info(f"Subtitle file validated and ensured UTF-8: {subtitle_path}")
        except UnicodeDecodeError:
            # Try to read with different encodings and convert to UTF-8
            logger.warning("Subtitle file is not UTF-8, attempting to convert...")
            for encoding in ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1252', 'latin-1', 'iso-8859-1']:
                try:
                    content = subtitle_path.read_text(encoding=encoding)
                    subtitle_path.write_text(content, encoding='utf-8')
                    logger.info(f"Converted subtitle from {encoding} to UTF-8")
                    break
                except:
                    continue
            else:
                raise SubtitleError("Could not decode subtitle file with any known encoding")
        
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
        
        Args:
            video_path: Path to input video
            subtitle_path: Path to subtitle file
            output_path: Optional output path
            progress_callback: Function(current_seconds, total_seconds) for progress
            cancel_check: Optional function() -> bool to check for cancellation
            
        Returns:
            Path to output video with burned subtitles
        """
        logger.info("Burning hard subtitles into video...")
        
        # Ensure text encoding is normalized and convert SRT->ASS for consistent Unicode shaping
        subtitle_path_for_burn = self.ensure_ass_subtitle(subtitle_path)
        
        if not output_path:
            output_path = DIRS['processing'] / f"{video_path.stem}_hardsubbed.mp4"
        
        # Import here to avoid circular dependency
        from config import PROCESSING_CONFIG
        low_memory = PROCESSING_CONFIG.get('low_memory_mode', False)
        
        try:
            # Escape subtitle path for FFmpeg filter
            # Windows paths need special handling
            subtitle_filter_path = str(subtitle_path_for_burn).replace('\\', '/').replace(':', '\\\\:')
            
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
            
            # Get project fonts directory
            project_fonts = DIRS.get('fonts', Path('Fonts'))
            if not isinstance(project_fonts, Path):
                project_fonts = Path('Fonts')
            
            # Create complex filter with subtitles + watermark text for first 10 seconds
            watermark_text = "This is MovieDownloadSL..."
            arial_path = project_fonts / 'arial.ttf'
            if arial_path.exists():
                arial_font = str(arial_path.absolute()).replace('\\', '\\\\\\\\').replace(':', '\\\\:')
            else:
                arial_font = 'C\\\\\\\\:/Windows/Fonts/arial.ttf'
            watermark_filter = f"drawtext=text='{watermark_text}':fontfile={arial_font}:fontsize=24:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=30:enable='lt(t,10)'"
            
            # Get temp directory for fonts.conf
            temp_dir = DIRS.get('temp', Path('temp'))
            if not isinstance(temp_dir, Path):
                temp_dir = Path('temp')
            temp_dir.mkdir(exist_ok=True)
            
            # Subtitle filter - libass will now find bindumathi from fonts.conf
            subtitle_file_escaped = self._escape_ffmpeg_filter_path(subtitle_path_for_burn)

            # Per Sinhala hard-burn best practice:
            # - Rely on ASS style (Fontname/size/colors) rather than FFmpeg force_style
            # - Keep filter minimal to reduce parsing/fontconfig edge cases
            subtitle_filter = f"subtitles=filename='{subtitle_file_escaped}':charenc=UTF-8"
            
            # Combine both filters: subtitles + watermark (watermark only shows for first 10 seconds)
            combined_filter = f"{subtitle_filter},{watermark_filter}"
            
            # FFmpeg command for hard subtitle burning with Unicode support + watermark
            # force_style sets font to support Sinhala/Unicode characters
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-vf', combined_filter,
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
            logger.warning("GÜán+Å HARD SUBTITLE BURNING IS VERY SLOW (10-30 min)!")
            logger.warning("=ƒÆí For production, use SOFT SUBTITLES (takes <1 minute)")
            logger.info("Processing every video frame with subtitle overlay...")
            
            # Get video duration for progress calculation
            video_info = self.get_video_info(video_path)
            total_duration = video_info.get('duration', 0)
            
            # Run with progress output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True
            )
            
            # Monitor progress with FFmpeg output parsing and cancellation check
            import re
            import time
            for line in process.stdout:
                # Check for cancellation
                if cancel_check and cancel_check():
                    logger.warning("Cancelling hard subtitle burning...")
                    process.terminate()
                    time.sleep(0.5)
                    if process.poll() is None:  # Still running
                        process.kill()
                    # Delete partial output file
                    if output_path.exists():
                        output_path.unlink()
                    raise SubtitleError("Hard subtitle burning cancelled by user")
                
                if 'time=' in line:
                    # Parse FFmpeg progress: time=00:01:23.45
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', line)
                    if time_match and total_duration > 0:
                        hours, minutes, seconds = map(float, time_match.groups())
                        current_seconds = hours * 3600 + minutes * 60 + seconds
                        
                        if progress_callback:
                            progress_callback(current_seconds, total_duration)
                        
                        # Log progress every 10%
                        progress_pct = (current_seconds / total_duration) * 100
                        if int(progress_pct) % 10 == 0:
                            logger.info(f"Progress: {progress_pct:.1f}% ({current_seconds:.0f}/{total_duration:.0f}s)")
            
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
            logger.info("G£ô Soft subtitles are FAST (~1 minute)")
            return self.embed_soft_subtitle(video_path, subtitle_path)
        else:
            logger.warning("GÜán+Å Hard subtitles are VERY SLOW (10-30 minutes)!")
            logger.warning("=ƒÆí Consider using soft subtitles for production")
            return self.embed_hard_subtitle(video_path, subtitle_path, progress_callback=progress_callback, cancel_check=cancel_check)


if __name__ == '__main__':
    # Test subtitle processor
    processor = SubtitleProcessor()
    print(f"Subtitle mode: {'Soft' if processor.soft_subtitle else 'Hard'}")
    print("Subtitle processor initialized successfully!")