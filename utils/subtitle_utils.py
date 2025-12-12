"""
Subtitle Utility Functions
Handles SRT to ASS conversion, font discovery, and FFmpeg compatibility
"""
import re
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Optional
from logger import logger


def srt_time_to_ass(t: str) -> str:
    """
    Convert SRT timestamp to ASS format
    "00:01:23,450" -> "0:01:23.45"
    """
    m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{1,3})", t.strip())
    if not m:
        raise ValueError(f"Invalid SRT timestamp: {t}")
    hh, mm, ss, ms = m.groups()
    cs = int(ms[:2].ljust(2, '0'))
    return f"{int(hh)}:{mm}:{ss}.{cs:02d}"


def escape_ass_text(line: str) -> str:
    r"""
    Escape text for ASS format and optionally convert HTML tags
    - Protects braces with backslashes
    - Converts HTML <font color> to ASS color overrides
    - Converts newlines to \N
    """
    if line is None:
        return ""
    
    # Protect ASS special characters
    line = line.replace("{", r"\{").replace("}", r"\}")
    
    # Convert HTML <font color="#RRGGBB"> to ASS {\c&HBBGGRR&}
    line = re.sub(
        r"<font\s+color=['\"]#?([0-9A-Fa-f]{6})['\"]>(.*?)</font>",
        lambda m: r"{\c&H" + m.group(1)[4:6] + m.group(1)[2:4] + m.group(1)[0:2] + r"&}" + m.group(2),
        line,
        flags=re.IGNORECASE
    )
    
    # Remove other HTML tags (bold, italic, etc.) - keep content
    line = re.sub(r"<b>(.*?)</b>", r"{\b1}\1{\b0}", line, flags=re.IGNORECASE)
    line = re.sub(r"<i>(.*?)</i>", r"{\i1}\1{\i0}", line, flags=re.IGNORECASE)
    line = re.sub(r"</?[^>]+>", "", line)  # Remove remaining tags
    
    # Convert newlines
    return line.replace("\r\n", "\n").replace("\n", r"\N")


def convert_srt_to_ass(
    srt_path: Path,
    ass_out: Path,
    fontname: str = "Bindumathi",
    fontsize: int = 36,
    playresx: int = 1920,
    playresy: int = 1080
) -> Path:
    """
    Convert SRT subtitle file to ASS format with proper Sinhala font styling
    
    Args:
        srt_path: Path to input SRT file
        ass_out: Path for output ASS file
        fontname: Font family name (default: Bindumathi)
        fontsize: Font size in points (default: 36)
        playresx: Video resolution width (default: 1920)
        playresy: Video resolution height (default: 1080)
        
    Returns:
        Path to created ASS file
    """
    logger.info(f"Converting SRT to ASS: {srt_path} -> {ass_out}")
    
    try:
        text = srt_path.read_text(encoding='utf-8', errors='replace')
    except UnicodeDecodeError:
        # Try alternate encodings
        for encoding in ['utf-8-sig', 'latin-1', 'cp1252']:
            try:
                text = srt_path.read_text(encoding=encoding, errors='replace')
                logger.info(f"Read SRT with {encoding} encoding")
                break
            except:
                continue
        else:
            raise ValueError(f"Could not decode SRT file: {srt_path}")
    
    # Split into blocks
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
    events = []
    
    for block in blocks:
        lines = block.splitlines()
        # Find the timestamp line
        time_line = next((l for l in lines if '-->' in l), None)
        if not time_line:
            continue
            
        try:
            start_s, end_s = [p.strip() for p in time_line.split('-->')]
            start = srt_time_to_ass(start_s)
            end = srt_time_to_ass(end_s)
        except ValueError as e:
            logger.warning(f"Skipping invalid timestamp: {time_line} - {e}")
            continue
        
        # Text lines are after the timestamp
        idx = lines.index(time_line)
        raw_text_lines = lines[idx+1:]
        text_joined = r"\N".join(escape_ass_text(ln) for ln in raw_text_lines)
        
        events.append((start, end, text_joined))
    
    logger.info(f"Converted {len(events)} subtitle events")
    
    # Build ASS file with proper header
    header = [
        "[Script Info]",
        "Title: Converted from SRT",
        "ScriptType: v4.00+",
        f"PlayResX: {playresx}",
        f"PlayResY: {playresy}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{fontname},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,40,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    
    with ass_out.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(header) + "\n")
        for start, end, t in events:
            fh.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{t}\n")
    
    logger.info(f"ASS file created successfully: {ass_out}")
    return ass_out


def find_font(
    candidate_names: list,
    fonts_dir: Path = Path("Fonts")
) -> Tuple[Optional[Path], str]:
    """
    Find a font file by searching candidate names
    
    Args:
        candidate_names: List of font filenames or family names to try
        fonts_dir: Project fonts directory
        
    Returns:
        Tuple of (font_path, font_family_name)
        font_path may be None if not found
    """
    logger.info(f"Searching for font from candidates: {candidate_names}")
    
    # 1) Check project fonts directory
    if fonts_dir.exists():
        for name in candidate_names:
            p = fonts_dir / name
            if p.exists():
                logger.info(f"Found font in project: {p}")
                return p.resolve(), name.replace('.ttf', '').replace('.otf', '')
            
            # Try with extensions
            for ext in (".ttf", ".otf"):
                p2 = fonts_dir / (name + ext)
                if p2.exists():
                    logger.info(f"Found font in project: {p2}")
                    return p2.resolve(), name
    
    # 2) Check Windows system fonts
    win_fonts = Path(r"C:\Windows\Fonts")
    if win_fonts.exists():
        for name in candidate_names:
            for ext in (".ttf", ".otf", ""):
                p = win_fonts / (name + ext)
                if p.exists():
                    logger.info(f"Found font in Windows: {p}")
                    return p.resolve(), name.replace('.ttf', '').replace('.otf', '')
    
    # 3) Return fallback path in fonts_dir (file may not exist)
    fallback = fonts_dir / (candidate_names[0] + ".ttf")
    logger.warning(f"Font not found, using fallback path: {fallback}")
    return fallback.resolve(), candidate_names[0]


def detect_ffmpeg_shaping() -> Dict[str, bool]:
    """
    Detect if FFmpeg has libass and HarfBuzz support for complex text shaping
    
    Returns:
        Dictionary with detection results:
        - ffmpeg_found: Whether ffmpeg is available
        - libass: Whether libass is compiled in
        - harfbuzz: Whether HarfBuzz shaping support is available
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        ver = result.stdout.lower()
        
        detection = {
            "ffmpeg_found": True,
            "libass": ("libass" in ver) or ("--enable-libass" in ver),
            "harfbuzz": ("harfbuzz" in ver) or ("--enable-libharfbuzz" in ver)
        }
        
        logger.info(f"FFmpeg shaping detection: {detection}")
        return detection
        
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to detect FFmpeg capabilities: {e}")
        return {"ffmpeg_found": False, "libass": False, "harfbuzz": False}


def escape_ffmpeg_path_for_filter(p: str) -> str:
    """
    Escape a file path for use in FFmpeg filter syntax
    Converts backslashes to forward slashes for cross-platform compatibility
    
    Args:
        p: File path string
        
    Returns:
        Escaped path safe for FFmpeg filters
    """
    # Convert to forward slashes (works on Windows too)
    return p.replace("\\", "/")


def validate_sinhala_font_support(font_path: Path) -> bool:
    """
    Basic check if a font file likely supports Sinhala glyphs
    
    Args:
        font_path: Path to font file
        
    Returns:
        True if font appears to support Sinhala (basic check only)
    """
    if not font_path.exists():
        logger.warning(f"Font file does not exist: {font_path}")
        return False
    
    # Basic check: file exists and has reasonable size
    size = font_path.stat().st_size
    if size < 10000:  # Too small to be a real font
        logger.warning(f"Font file suspiciously small: {font_path} ({size} bytes)")
        return False
    
    logger.info(f"Font file appears valid: {font_path} ({size} bytes)")
    
    # Optional: Use fonttools to check for Sinhala cmap if available
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(str(font_path))
        cmap = font.getBestCmap()
        if cmap:
            # Check for some common Sinhala codepoints (U+0D80-U+0DFF)
            sinhala_test_chars = [0x0D85, 0x0D9A, 0x0DB8, 0x0DCF]  # Some basic Sinhala chars
            has_sinhala = any(char in cmap for char in sinhala_test_chars)
            logger.info(f"Font Sinhala glyph check: {has_sinhala}")
            return has_sinhala
    except ImportError:
        logger.debug("fonttools not available, skipping glyph validation")
    except Exception as e:
        logger.warning(f"Could not validate font glyphs: {e}")
    
    return True  # Assume valid if we can't check
