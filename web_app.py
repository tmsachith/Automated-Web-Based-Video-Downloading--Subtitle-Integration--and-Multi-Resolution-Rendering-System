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
cancelled_jobs = set()  # Track cancelled job IDs
queued_jobs = []  # Queue of pending jobs
current_running_job = None  # Track the single running job

# Allowed subtitle extensions
ALLOWED_EXTENSIONS = {'.srt', '.ass', '.vtt', '.sub', '.ssa'}

# Progress tracking
job_progress = {}  # {job_id: {'current': 0, 'total': 100, 'task': 'description'}}

# Job persistence file
JOBS_FILE = DIRS['logs'] / 'jobs_state.json'


def save_jobs_to_disk():
    """Save current job state to disk"""
    try:
        state = {
            'active_jobs': active_jobs,
            'completed_jobs': completed_jobs,
            'cancelled_jobs': list(cancelled_jobs),
            'timestamp': datetime.now().isoformat()
        }
        with open(JOBS_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Jobs saved to disk: {len(active_jobs)} active, {len(completed_jobs)} completed")
    except Exception as e:
        logger.error(f"Failed to save jobs to disk: {e}")


def load_jobs_from_disk():
    """Load job state from disk on startup"""
    global active_jobs, completed_jobs, cancelled_jobs
    
    try:
        if JOBS_FILE.exists():
            with open(JOBS_FILE, 'r') as f:
                state = json.load(f)
            
            # Restore completed jobs
            completed_jobs = state.get('completed_jobs', {})
            
            # Mark active jobs as interrupted (they won't resume)
            old_active = state.get('active_jobs', {})
            for job_id, job_data in old_active.items():
                completed_jobs[job_id] = {
                    'status': 'interrupted',
                    'error': 'Server was redeployed while job was processing',
                    'timestamp': datetime.now().isoformat(),
                    'tasks': job_data.get('tasks', []),
                    'original_data': job_data
                }
            
            cancelled_jobs = set(state.get('cancelled_jobs', []))
            
            logger.info(f"Jobs loaded from disk: {len(completed_jobs)} total jobs, {len(old_active)} were interrupted")
            
            # Save updated state
            save_jobs_to_disk()
            
            return True
    except Exception as e:
        logger.error(f"Failed to load jobs from disk: {e}")
        return False
    
    return False


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
        self.cancelled = False
    
    def update_progress(self, task, current, total, task_status='in-progress', speed=0, eta=0):
        """Update job progress"""
        if self.job_id in active_jobs:
            active_jobs[self.job_id]['progress'] = {
                'task': task,
                'current': current,
                'total': total,
                'percentage': int((current / total * 100) if total > 0 else 0),
                'task_status': task_status,
                'speed': speed,  # bytes per second
                'eta': eta  # seconds remaining
            }
    
    def update_task_list(self, tasks):
        """Update task list for the job"""
        if self.job_id in active_jobs:
            active_jobs[self.job_id]['tasks'] = tasks
    
    def check_cancelled(self):
        """Check if job was cancelled"""
        return self.job_id in cancelled_jobs
    
    def run(self):
        """Execute the processing job"""
        global current_running_job
        
        try:
            # Mark this job as currently running
            current_running_job = self.job_id
            
            # Initialize tasks
            tasks = [
                {'name': 'Download Video', 'status': 'pending'},
                {'name': 'Download/Upload Subtitle', 'status': 'pending'},
                {'name': 'Process Subtitles', 'status': 'pending'},
                {'name': 'Encode Videos', 'status': 'pending'}
            ]
            
            active_jobs[self.job_id]['status'] = 'processing'
            active_jobs[self.job_id]['stage'] = 'Initializing'
            self.update_task_list(tasks)
            
            if self.check_cancelled():
                raise Exception("Job cancelled by user")
            
            if self.use_file:
                # Process with uploaded file
                from downloader import Downloader
                from pathlib import Path
                
                downloader = Downloader()
                
                # Download video
                tasks[0]['status'] = 'in-progress'
                self.update_task_list(tasks)
                active_jobs[self.job_id]['stage'] = 'Downloading video'
                self.update_progress('Downloading video', 0, 100)
                
                video_path = downloader.download_file_with_progress(
                    self.video_url,
                    DIRS['downloads'],
                    file_type='video',
                    progress_callback=lambda cur, tot, spd=0, eta=0: self.update_progress('Downloading video', cur, tot, 'in-progress', spd, eta)
                )
                
                if self.check_cancelled():
                    raise Exception("Job cancelled by user")
                
                tasks[0]['status'] = 'completed'
                tasks[1]['status'] = 'completed'  # Subtitle already uploaded
                self.update_task_list(tasks)
                
                # Subtitle is already uploaded
                subtitle_path = Path(self.subtitle_source)
                
                # Continue with subtitle processing
                from subtitle_processor import SubtitleProcessor
                processor = SubtitleProcessor()
                
                if self.check_cancelled():
                    raise Exception("Job cancelled by user")
                
                tasks[2]['status'] = 'in-progress'
                self.update_task_list(tasks)
                active_jobs[self.job_id]['stage'] = 'Processing subtitles'
                
                # Show initial progress immediately
                self.update_progress('Processing subtitles (this may take several minutes)', 10, 100, 'in-progress')
                import time
                time.sleep(0.5)  # Small delay to ensure UI updates
                
                self.update_progress('Burning subtitles into video frames', 30, 100, 'in-progress')
                
                # Add progress callback for hard subtitle burning
                def subtitle_progress(current_sec, total_sec):
                    if total_sec > 0:
                        # Map 30-90% of progress bar to subtitle burning
                        percentage = 30 + int((current_sec / total_sec) * 60)
                        self.update_progress(f'Burning subtitles ({int(current_sec)}s / {int(total_sec)}s)', percentage, 100, 'in-progress')
                
                processed_video = processor.process_subtitle(
                    video_path,
                    subtitle_path,
                    self.use_soft_subtitle,
                    progress_callback=subtitle_progress if not self.use_soft_subtitle else None
                )
                
                self.update_progress('Processing subtitles', 100, 100, 'completed')
                tasks[2]['status'] = 'completed'
                self.update_task_list(tasks)
                
                # Encode to multiple resolutions
                from video_encoder import VideoEncoder
                encoder = VideoEncoder()
                
                if self.check_cancelled():
                    raise Exception("Job cancelled by user")
                
                tasks[3]['status'] = 'in-progress'
                self.update_task_list(tasks)
                active_jobs[self.job_id]['stage'] = 'Encoding videos'
                
                output_files = {}
                total_resolutions = len(self.resolutions)
                for idx, resolution in enumerate(self.resolutions):
                    if self.check_cancelled():
                        raise Exception("Job cancelled by user")
                    
                    # Show progress for current encoding
                    current_percentage = int((idx / total_resolutions) * 100)
                    self.update_progress(f'Encoding {resolution}', current_percentage, 100, 'in-progress')
                    
                    output_files[resolution] = encoder.encode_single_resolution(
                        processed_video,
                        resolution
                    )
                    
                    # Update after completion of this resolution
                    completed_percentage = int(((idx + 1) / total_resolutions) * 100)
                    self.update_progress(f'Encoding videos', completed_percentage, 100, 'in-progress')
                
                tasks[3]['status'] = 'completed'
                self.update_task_list(tasks)
                
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
            
            # Mark all tasks completed
            for task in tasks:
                task['status'] = 'completed'
            self.update_task_list(tasks)
            self.update_progress('Completed', 100, 100, 'completed')
            
            # Move to completed jobs with output file info
            completed_jobs[self.job_id] = {
                'status': 'completed',
                'results': results,
                'timestamp': datetime.now().isoformat(),
                'tasks': tasks,
                'output_files': results.get('output_files', {})
            }
            
            if self.job_id in active_jobs:
                del active_jobs[self.job_id]
            
            # Clear running job marker
            current_running_job = None
            
            # Save state to disk
            save_jobs_to_disk()
                
        except Exception as e:
            logger.error(f"Job {self.job_id} failed: {e}")
            
            is_cancelled = 'cancelled' in str(e).lower()
            
            completed_jobs[self.job_id] = {
                'status': 'cancelled' if is_cancelled else 'failed',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'tasks': tasks if 'tasks' in locals() else []
            }
            
            if self.job_id in active_jobs:
                del active_jobs[self.job_id]
            
            if self.job_id in cancelled_jobs:
                cancelled_jobs.remove(self.job_id)
            
            # Clear running job marker
            current_running_job = None
            
            # Save state to disk
            save_jobs_to_disk()


@app.route('/')
def index():
    """Render main page"""
    return render_template('index.html')


@app.route('/api/submit', methods=['POST'])
def submit_job():
    """Submit a new processing job"""
    global current_running_job
    
    try:
        # Check if a job is already running
        if current_running_job is not None:
            return jsonify({
                'success': False,
                'error': 'A job is already running. Please wait for it to complete or cancel it first.',
                'running_job_id': current_running_job
            }), 409  # Conflict status
        
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
        
        # Save state to disk
        save_jobs_to_disk()
        
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
    global current_running_job
    
    try:
        # Check if a job is already running
        if current_running_job is not None:
            return jsonify({
                'success': False,
                'error': 'A job is already running. Please wait for it to complete or cancel it first.',
                'running_job_id': current_running_job
            }), 409  # Conflict status
        
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
        
        # Save state to disk
        save_jobs_to_disk()
        
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


@app.route('/api/jobs/all')
def get_all_jobs():
    """Get all jobs (active and completed)"""
    all_jobs = []
    
    # Add active jobs
    for job_id, job_data in active_jobs.items():
        all_jobs.append({
            'job_id': job_id,
            'status': 'active',
            'details': job_data
        })
    
    # Add completed jobs
    for job_id, job_data in completed_jobs.items():
        all_jobs.append({
            'job_id': job_id,
            'status': job_data.get('status', 'completed'),
            'details': job_data
        })
    
    # Sort by timestamp (newest first)
    all_jobs.sort(key=lambda x: x['details'].get('timestamp', ''), reverse=True)
    
    return jsonify({
        'success': True,
        'jobs': all_jobs,
        'total': len(all_jobs),
        'active_count': len(active_jobs),
        'completed_count': len(completed_jobs)
    })


@app.route('/api/jobs/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    """Cancel an active job"""
    if job_id in active_jobs:
        cancelled_jobs.add(job_id)
        active_jobs[job_id]['status'] = 'cancelling'
        active_jobs[job_id]['stage'] = 'Cancelling...'
        
        return jsonify({
            'success': True,
            'message': f'Job {job_id} is being cancelled'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Job not found or already completed'
        }), 404


@app.route('/api/download/<job_id>/<resolution>')
def download_video(job_id, resolution):
    """Download a processed video file"""
    if job_id in completed_jobs:
        job_data = completed_jobs[job_id]
        if 'output_files' in job_data:
            file_path = job_data['output_files'].get(resolution)
            if file_path and os.path.exists(file_path):
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=os.path.basename(file_path)
                )
    
    return jsonify({'error': 'File not found'}), 404


@app.route('/api/stream/<job_id>/<resolution>')
def stream_video(job_id, resolution):
    """Stream a processed video file"""
    if job_id in completed_jobs:
        job_data = completed_jobs[job_id]
        if 'output_files' in job_data:
            file_path = job_data['output_files'].get(resolution)
            if file_path and os.path.exists(file_path):
                return send_file(
                    file_path,
                    mimetype='video/mp4',
                    as_attachment=False
                )
    
    return jsonify({'error': 'File not found'}), 404


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


@app.route('/api/files/browse')
def browse_files():
    """Browse all files in downloads and outputs directories"""
    try:
        files_info = {
            'downloads': [],
            'outputs': {},
            'total_size': 0
        }
        
        # List downloads folder
        if DIRS['downloads'].exists():
            for file_path in DIRS['downloads'].iterdir():
                if file_path.is_file():
                    size = file_path.stat().st_size
                    files_info['downloads'].append({
                        'name': file_path.name,
                        'size': size,
                        'size_mb': round(size / (1024 * 1024), 2),
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                        'path': str(file_path.relative_to(DIRS['downloads'].parent))
                    })
                    files_info['total_size'] += size
        
        # List outputs folder by resolution
        if DIRS['outputs'].exists():
            for resolution_dir in DIRS['outputs'].iterdir():
                if resolution_dir.is_dir():
                    resolution_files = []
                    for file_path in resolution_dir.iterdir():
                        if file_path.is_file():
                            size = file_path.stat().st_size
                            resolution_files.append({
                                'name': file_path.name,
                                'size': size,
                                'size_mb': round(size / (1024 * 1024), 2),
                                'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                                'path': str(file_path.relative_to(DIRS['outputs'].parent))
                            })
                            files_info['total_size'] += size
                    files_info['outputs'][resolution_dir.name] = resolution_files
        
        files_info['total_size_mb'] = round(files_info['total_size'] / (1024 * 1024), 2)
        files_info['total_size_gb'] = round(files_info['total_size'] / (1024 * 1024 * 1024), 2)
        
        return jsonify({
            'success': True,
            'files': files_info
        })
    except Exception as e:
        logger.error(f"Failed to browse files: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/files/download/<path:filepath>')
def download_file_direct(filepath):
    """Download any file by relative path"""
    try:
        # Security: ensure path doesn't escape base directory
        base_dir = DIRS['downloads'].parent
        file_path = (base_dir / filepath).resolve()
        
        if not str(file_path).startswith(str(base_dir)):
            return jsonify({'error': 'Invalid file path'}), 403
        
        if not file_path.exists():
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=file_path.name
        )
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/status')
def system_status():
    """Get system status including running job and capacity"""
    return jsonify({
        'success': True,
        'has_running_job': current_running_job is not None,
        'running_job_id': current_running_job,
        'active_jobs_count': len(active_jobs),
        'completed_jobs_count': len(completed_jobs),
        'can_submit_new_job': current_running_job is None,
        'system_info': {
            'plan': 'Railway Free (2 vCPU, 1GB RAM)',
            'max_concurrent_jobs': 1,
            'recommendation': 'Close browser tab after submitting - jobs run in background'
        }
    })


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
    
    # Load previous job state
    print("\nLoading previous job state...")
    if load_jobs_from_disk():
        print(f"✓ Loaded {len(completed_jobs)} jobs from previous session")
        interrupted_count = sum(1 for job in completed_jobs.values() if job.get('status') == 'interrupted')
        if interrupted_count > 0:
            print(f"⚠ {interrupted_count} jobs were interrupted by server restart")
    else:
        print("No previous jobs found")
    
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
