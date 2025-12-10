"""
Download Manager for Video and Subtitle Files
"""
import requests
import os
from pathlib import Path
from typing import Tuple, Optional
from urllib.parse import urlparse, unquote
import mimetypes
from tqdm import tqdm
import time

from config import DOWNLOAD_CONFIG, DIRS, SUPPORTED_FORMATS
from logger import logger, DownloadError, ValidationError


class Downloader:
    """Handles downloading video and subtitle files from URLs"""
    
    def __init__(self):
        self.chunk_size = DOWNLOAD_CONFIG['chunk_size']
        self.timeout = DOWNLOAD_CONFIG['timeout']
        self.max_retries = DOWNLOAD_CONFIG['max_retries']
        self.headers = {
            'User-Agent': DOWNLOAD_CONFIG['user_agent']
        }
    
    def validate_url(self, url: str) -> bool:
        """
        Validate if URL is properly formatted
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    def get_filename_from_url(self, url: str, content_type: str = None) -> str:
        """
        Extract filename from URL or generate from content type
        
        Args:
            url: Download URL
            content_type: MIME content type
            
        Returns:
            Filename string
        """
        # Try to get filename from URL
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        
        # If no filename in URL, generate one
        if not filename or '.' not in filename:
            extension = mimetypes.guess_extension(content_type) if content_type else '.mp4'
            filename = f"download_{hash(url) % 100000}{extension}"
        
        return filename
    
    def get_file_extension(self, filename: str) -> str:
        """Get file extension in lowercase"""
        return Path(filename).suffix.lower()
    
    def validate_file_type(self, filename: str, file_type: str) -> bool:
        """
        Validate if file has supported extension
        
        Args:
            filename: File name to check
            file_type: 'video' or 'subtitle'
            
        Returns:
            True if supported, False otherwise
        """
        extension = self.get_file_extension(filename)
        supported = SUPPORTED_FORMATS.get(file_type, [])
        
        if extension not in supported:
            logger.warning(
                f"File extension '{extension}' not in supported {file_type} formats: {supported}"
            )
            return False
        return True
    
    def download_file_with_progress(
        self,
        url: str,
        destination: Path,
        file_type: str = 'video',
        filename: Optional[str] = None,
        progress_callback=None,
        cancel_check=None
    ) -> Path:
        """
        Download file from URL with progress callback
        
        Args:
            url: Download URL
            destination: Destination directory
            file_type: Type of file ('video' or 'subtitle')
            filename: Optional custom filename
            progress_callback: Function(current_bytes, total_bytes, speed, eta) for progress updates
            cancel_check: Function() -> bool to check if download should be cancelled
            
        Returns:
            Path to downloaded file
        """
        if not self.validate_url(url):
            raise ValidationError(f"Invalid URL: {url}")
        
        logger.info(f"Starting download from: {url}")
        
        attempt = 0
        last_error = None
        
        while attempt < self.max_retries:
            try:
                # Send HEAD request to get file info
                head_response = requests.head(
                    url, 
                    headers=self.headers, 
                    timeout=self.timeout,
                    allow_redirects=True,
                    verify=DOWNLOAD_CONFIG['verify_ssl']
                )
                
                content_type = head_response.headers.get('Content-Type', '')
                content_length = int(head_response.headers.get('Content-Length', 0))
                
                # Determine filename
                if not filename:
                    filename = self.get_filename_from_url(url, content_type)
                
                file_path = destination / filename
                
                logger.info(f"Downloading to: {file_path}")
                logger.info(f"File size: {content_length / (1024*1024):.2f} MB")
                
                # Download with progress callback
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    stream=True,
                    verify=DOWNLOAD_CONFIG['verify_ssl']
                )
                response.raise_for_status()
                
                downloaded = 0
                start_time = time.time()
                last_update = start_time
                last_downloaded = 0
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            # Check for cancellation before writing chunk
                            if cancel_check and cancel_check():
                                logger.warning("Download cancelled by user")
                                f.close()
                                if file_path.exists():
                                    file_path.unlink()  # Delete partial file
                                raise DownloadError("Download cancelled by user")
                            
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Calculate speed and ETA every second
                            current_time = time.time()
                            if progress_callback and (current_time - last_update >= 1.0 or downloaded == content_length):
                                elapsed = current_time - start_time
                                speed = downloaded / elapsed if elapsed > 0 else 0  # bytes per second
                                
                                if speed > 0 and downloaded < content_length:
                                    remaining_bytes = content_length - downloaded
                                    eta_seconds = remaining_bytes / speed
                                else:
                                    eta_seconds = 0
                                
                                progress_callback(downloaded, content_length, speed, eta_seconds)
                                last_update = current_time
                                last_downloaded = downloaded
                
                logger.info(f"Download completed: {file_path}")
                return file_path
                
            except Exception as e:
                attempt += 1
                last_error = e
                logger.warning(f"Download attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    logger.info(f"Retrying... ({attempt}/{self.max_retries})")
        
        raise DownloadError(f"Download failed after {self.max_retries} attempts: {last_error}")
    
    def download_file(
        self, 
        url: str, 
        destination: Path, 
        file_type: str = 'video',
        filename: Optional[str] = None
    ) -> Path:
        """
        Download file from URL with progress tracking
        
        Args:
            url: Download URL
            destination: Destination directory
            file_type: Type of file ('video' or 'subtitle')
            filename: Optional custom filename
            
        Returns:
            Path to downloaded file
            
        Raises:
            DownloadError: If download fails
            ValidationError: If URL or file type is invalid
        """
        if not self.validate_url(url):
            raise ValidationError(f"Invalid URL: {url}")
        
        logger.info(f"Starting download from: {url}")
        
        attempt = 0
        last_error = None
        
        while attempt < self.max_retries:
            try:
                # Send HEAD request to get file info
                head_response = requests.head(
                    url, 
                    headers=self.headers, 
                    timeout=self.timeout,
                    allow_redirects=True,
                    verify=DOWNLOAD_CONFIG['verify_ssl']
                )
                
                content_type = head_response.headers.get('Content-Type', '')
                content_length = int(head_response.headers.get('Content-Length', 0))
                
                # Determine filename
                if not filename:
                    filename = self.get_filename_from_url(url, content_type)
                
                # Validate file type
                if not self.validate_file_type(filename, file_type):
                    logger.warning(f"Proceeding with potentially unsupported {file_type} format")
                
                file_path = destination / filename
                
                logger.info(f"Downloading to: {file_path}")
                logger.info(f"File size: {content_length / (1024*1024):.2f} MB")
                
                # Download with progress bar
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    stream=True,
                    verify=DOWNLOAD_CONFIG['verify_ssl']
                )
                response.raise_for_status()
                
                # Use tqdm for progress tracking
                with open(file_path, 'wb') as f:
                    with tqdm(
                        total=content_length,
                        unit='B',
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=f"Downloading {filename}"
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
                
                # Verify download
                downloaded_size = file_path.stat().st_size
                if content_length > 0 and downloaded_size != content_length:
                    raise DownloadError(
                        f"Download incomplete. Expected {content_length} bytes, "
                        f"got {downloaded_size} bytes"
                    )
                
                logger.info(f"Download completed: {file_path} ({downloaded_size / (1024*1024):.2f} MB)")
                return file_path
                
            except requests.RequestException as e:
                attempt += 1
                last_error = e
                logger.warning(f"Download attempt {attempt} failed: {e}")
                
                if attempt < self.max_retries:
                    logger.info(f"Retrying... ({attempt}/{self.max_retries})")
                else:
                    raise DownloadError(
                        f"Failed to download after {self.max_retries} attempts: {last_error}"
                    )
            
            except Exception as e:
                raise DownloadError(f"Unexpected error during download: {e}")
    
    def download_video_and_subtitle(
        self, 
        video_url: str, 
        subtitle_url: str
    ) -> Tuple[Path, Path]:
        """
        Download both video and subtitle files
        
        Args:
            video_url: Video download URL
            subtitle_url: Subtitle download URL
            
        Returns:
            Tuple of (video_path, subtitle_path)
        """
        logger.info("Starting video and subtitle download...")
        
        try:
            # Download video
            video_path = self.download_file(
                video_url,
                DIRS['downloads'],
                file_type='video'
            )
            
            # Download subtitle
            subtitle_path = self.download_file(
                subtitle_url,
                DIRS['downloads'],
                file_type='subtitle'
            )
            
            logger.info("Both files downloaded successfully!")
            return video_path, subtitle_path
            
        except Exception as e:
            logger.error(f"Failed to download files: {e}")
            raise


def test_downloader():
    """Test the downloader with sample URLs"""
    downloader = Downloader()
    
    # Test URL validation
    valid_url = "https://example.com/video.mp4"
    invalid_url = "not-a-url"
    
    print(f"Valid URL test: {downloader.validate_url(valid_url)}")
    print(f"Invalid URL test: {downloader.validate_url(invalid_url)}")
    
    # Test filename extraction
    url_with_filename = "https://example.com/path/to/movie.mp4?param=value"
    filename = downloader.get_filename_from_url(url_with_filename)
    print(f"Extracted filename: {filename}")
    
    # Test file type validation
    print(f"Video validation (.mp4): {downloader.validate_file_type('test.mp4', 'video')}")
    print(f"Subtitle validation (.srt): {downloader.validate_file_type('test.srt', 'subtitle')}")
    print(f"Invalid validation (.txt): {downloader.validate_file_type('test.txt', 'video')}")


if __name__ == '__main__':
    test_downloader()
