"""
Flask Web Application for Video Processing System
"""
from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
from werkzeug.utils import secure_filename
import threading
from datetime import datetime
import json
import os

from config import WEB_CONFIG, DIRS
from main import VideoProcessingPipeline
from logger import logger

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = WEB_CONFIG['max_upload_size']
app.config['UPLOAD_FOLDER'] = DIRS['downloads']

# Store active jobs
active_jobs = {}
completed_jobs = {}

# Allowed subtitle extensions
ALLOWED_EXTENSIONS = {'.srt', '.ass', '.vtt', '.sub', '.ssa'}


class JobProcessor(threading.Thread):
    """Background thread for processing video jobs"""
    
    def __init__(self, job_id, video_url, subtitle_source, resolutions, use_soft_subtitle, use_file=False):
        super().__init__()
        self.job_id = job_id
        self.video_url = video_url
        self.subtitle_source = subtitle_source  # Can be URL or file path
        self.resolutions = resolutions
        self.use_soft_subtitle = use_soft_subtitle
        self.use_file = use_file  # True if subtitle_source is a file path
        self.pipeline = VideoProcessingPipeline()
    
    def run(self):
        """Execute the processing job"""
        try:
            active_jobs[self.job_id]['status'] = 'processing'
            active_jobs[self.job_id]['stage'] = 'Downloading files' if not self.use_file else 'Processing files'
            
            if self.use_file:
                # Process with uploaded file
                from downloader import Downloader
                from pathlib import Path
                
                downloader = Downloader()
                
                # Download video
                active_jobs[self.job_id]['stage'] = 'Downloading video'
                video_path = downloader.download_file(
                    self.video_url,
                    DIRS['downloads'],
                    file_type='video'
                )
                
                # Subtitle is already uploaded
                subtitle_path = Path(self.subtitle_source)
                
                # Continue with subtitle processing
                from subtitle_processor import SubtitleProcessor
                processor = SubtitleProcessor()
                
                active_jobs[self.job_id]['stage'] = 'Processing subtitles'
                processed_video = processor.process_subtitle(
                    video_path,
                    subtitle_path,
                    self.use_soft_subtitle
                )
                
                # Encode to multiple resolutions
                from video_encoder import VideoEncoder
                encoder = VideoEncoder()
                
                active_jobs[self.job_id]['stage'] = 'Encoding videos'
                output_files = encoder.encode_all_resolutions(
                    processed_video,
                    self.resolutions
                )
                
                results = {
                    'job_id': self.job_id,
                    'status': 'success',
                    'video_url': self.video_url,
                    'subtitle_file': str(subtitle_path),
                    'output_files': {res: str(path) for res, path in output_files.items()},
                    'total_output_files': len(output_files)
                }
            else:
                # Original URL-based processing
                results = self.pipeline.process_video(
                    self.video_url,
                    self.subtitle_source,
                    self.resolutions,
                    self.use_soft_subtitle
                )
            
            # Move to completed jobs
            completed_jobs[self.job_id] = {
                'status': 'completed',
                'results': results,
                'timestamp': datetime.now().isoformat()
            }
            
            if self.job_id in active_jobs:
                del active_jobs[self.job_id]
                
        except Exception as e:
            logger.error(f"Job {self.job_id} failed: {e}")
            completed_jobs[self.job_id] = {
                'status': 'failed',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
            
            if self.job_id in active_jobs:
                del active_jobs[self.job_id]


@app.route('/')
def index():
    """Render main page"""
    return render_template('index.html')


@app.route('/api/submit', methods=['POST'])
def submit_job():
    """Submit a new processing job"""
    try:
        data = request.json
        
        video_url = data.get('video_url')
        subtitle_url = data.get('subtitle_url')
        resolutions = data.get('resolutions', ['360p', '480p', '720p', '1080p'])
        use_soft_subtitle = data.get('soft_subtitle', True)
        
        # Validate inputs
        if not video_url or not subtitle_url:
            return jsonify({
                'success': False,
                'error': 'Both video and subtitle URLs are required'
            }), 400
        
        # Generate job ID
        from main import VideoProcessingPipeline
        temp_pipeline = VideoProcessingPipeline()
        job_id = temp_pipeline.generate_job_id()
        
        # Create job entry
        active_jobs[job_id] = {
            'status': 'queued',
            'video_url': video_url,
            'subtitle_url': subtitle_url,
            'resolutions': resolutions,
            'soft_subtitle': use_soft_subtitle,
            'timestamp': datetime.now().isoformat(),
            'stage': 'Queued'
        }
        
        # Start processing thread
        processor = JobProcessor(job_id, video_url, subtitle_url, resolutions, use_soft_subtitle)
        processor.start()
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job submitted successfully'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/submit_with_file', methods=['POST'])
def submit_job_with_file():
    """Submit a new processing job with uploaded subtitle file"""
    try:
        video_url = request.form.get('video_url')
        subtitle_file = request.files.get('subtitle_file')
        resolutions = json.loads(request.form.get('resolutions', '["360p", "480p", "720p", "1080p"]'))
        use_soft_subtitle = request.form.get('soft_subtitle', 'true').lower() == 'true'
        
        # Validate inputs
        if not video_url:
            return jsonify({
                'success': False,
                'error': 'Video URL is required'
            }), 400
        
        if not subtitle_file:
            return jsonify({
                'success': False,
                'error': 'Subtitle file is required'
            }), 400
        
        # Validate file extension
        filename = secure_filename(subtitle_file.filename)
        file_ext = Path(filename).suffix.lower()
        
        if file_ext not in ALLOWED_EXTENSIONS:
            return jsonify({
                'success': False,
                'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Save uploaded file
        from main import VideoProcessingPipeline
        temp_pipeline = VideoProcessingPipeline()
        job_id = temp_pipeline.generate_job_id()
        
        subtitle_path = DIRS['downloads'] / f"{job_id}_{filename}"
        subtitle_file.save(str(subtitle_path))
        
        logger.info(f"Subtitle file uploaded: {subtitle_path}")
        
        # Create job entry
        active_jobs[job_id] = {
            'status': 'queued',
            'video_url': video_url,
            'subtitle_file': str(subtitle_path),
            'resolutions': resolutions,
            'soft_subtitle': use_soft_subtitle,
            'timestamp': datetime.now().isoformat(),
            'stage': 'Queued'
        }
        
        # Start processing thread with file path instead of URL
        processor = JobProcessor(job_id, video_url, str(subtitle_path), resolutions, use_soft_subtitle, use_file=True)
        processor.start()
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job submitted successfully with uploaded file'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit job with file: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/status/<job_id>')
def job_status(job_id):
    """Get status of a specific job"""
    # Check active jobs
    if job_id in active_jobs:
        return jsonify({
            'job_id': job_id,
            'status': 'active',
            'details': active_jobs[job_id]
        })
    
    # Check completed jobs
    if job_id in completed_jobs:
        return jsonify({
            'job_id': job_id,
            'status': 'completed',
            'details': completed_jobs[job_id]
        })
    
    return jsonify({
        'job_id': job_id,
        'status': 'not_found',
        'error': 'Job not found'
    }), 404


@app.route('/api/jobs')
def list_jobs():
    """List all jobs"""
    return jsonify({
        'active': active_jobs,
        'completed': completed_jobs
    })


@app.route('/api/download/<job_id>/<resolution>')
def download_file(job_id, resolution):
    """Download processed video file"""
    if job_id not in completed_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = completed_jobs[job_id]
    
    if job['status'] != 'completed':
        return jsonify({'error': 'Job not completed'}), 400
    
    output_files = job['results'].get('output_files', {})
    
    if resolution not in output_files:
        return jsonify({'error': 'Resolution not found'}), 404
    
    file_path = Path(output_files[resolution])
    
    if not file_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_path.name
    )


@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_jobs': len(active_jobs),
        'completed_jobs': len(completed_jobs)
    })


def run_web_app():
    """Start the Flask web application"""
    print("\n" + "="*80)
    print("AUTOMATED VIDEO PROCESSING SYSTEM - WEB INTERFACE")
    print("="*80)
    print(f"\nStarting web server on http://{WEB_CONFIG['host']}:{WEB_CONFIG['port']}")
    print("\nPress Ctrl+C to stop the server\n")
    print("="*80 + "\n")
    
    app.run(
        host=WEB_CONFIG['host'],
        port=WEB_CONFIG['port'],
        debug=WEB_CONFIG['debug']
    )


if __name__ == '__main__':
    run_web_app()
