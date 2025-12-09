# Railway File Storage Guide

## Understanding Railway Storage

### ⚠️ CRITICAL: Railway Storage is Ephemeral

**What this means:**
- Files are stored in the container's filesystem
- **ALL FILES ARE DELETED** when:
  - You redeploy your app
  - Railway restarts your container
  - You scale up/down
  - Container crashes and restarts

**You CANNOT access files via SSH or FTP on Railway free tier**

---

## How to Access Files on Railway

### Method 1: File Browser (Web Interface) ✅

**We just added this feature!**

1. Open your Railway app URL: `https://your-app.railway.app`
2. Scroll down to "📁 File Browser (Railway Storage)"
3. Click "🔄 Refresh Files"
4. You'll see:

```
💾 Total Storage: 450.5 MB (0.44 GB)
⚠️ Railway storage is ephemeral - files are deleted on restart/redeploy

📥 Downloads Folder (2 files)
┌─────────────────────────────────────────────┐
│ video_20251209.mp4                          │
│ 350.5 MB • 12/9/2025, 6:45:30 PM   ⬇️ Download │
├─────────────────────────────────────────────┤
│ subtitle_20251209.srt                       │
│ 0.05 MB • 12/9/2025, 6:45:35 PM    ⬇️ Download │
└─────────────────────────────────────────────┘

🎬 Output Videos
720p (1 files)
┌─────────────────────────────────────────────┐
│ video_20251209_720p.mp4                     │
│ 100.0 MB • 12/9/2025, 6:50:12 PM           │
│                          ▶️ Stream  ⬇️ Download │
└─────────────────────────────────────────────┘
```

### Method 2: Job Cards (Direct Downloads) ✅

After job completes, each job card shows:
```
📹 Output Videos:
┌─────────────────────┐
│ 360p               │
│ ▶️ Stream  ⬇️ Download │
├─────────────────────┤
│ 480p               │
│ ▶️ Stream  ⬇️ Download │
└─────────────────────┘
```

### Method 3: Direct API Endpoints ✅

**List all files:**
```bash
curl https://your-app.railway.app/api/files/browse
```

**Download specific file:**
```bash
curl -O https://your-app.railway.app/api/files/download/outputs/720p/video.mp4
```

---

## File Locations on Railway

### Local Development
```
D:\Projects\Your-Project\
├── downloads/          # Downloaded videos & subtitles
│   ├── video_123.mp4
│   └── subtitle_123.srt
├── outputs/           # Processed videos
│   ├── 360p/
│   ├── 480p/
│   ├── 720p/
│   └── 1080p/
├── processing/        # Temporary files during encoding
├── logs/             # Log files & job state
└── temp/             # Temporary download chunks
```

### Railway Container
```
/app/                  # Your application root
├── downloads/         # ⚠️ EPHEMERAL - deleted on restart
├── outputs/          # ⚠️ EPHEMERAL - deleted on restart
├── processing/       # ⚠️ EPHEMERAL - deleted on restart
├── logs/             # ⚠️ EPHEMERAL - deleted on restart
└── temp/             # ⚠️ EPHEMERAL - deleted on restart
```

**Railway free tier does NOT provide:**
- SSH access to browse files
- FTP/SFTP access
- Persistent volumes
- File system backups

---

## Solutions for Production

### Option 1: Download Files Immediately (Current Setup) ✅

**Workflow:**
1. Submit job on Railway
2. Wait for completion (check status periodically)
3. **Immediately download** all output files via File Browser
4. Store files on your local computer or cloud storage
5. Files may be deleted on next Railway restart

**Pros:**
- Free
- Works with current setup
- Simple workflow

**Cons:**
- Must manually download files
- Files deleted on restart
- No long-term storage on Railway

### Option 2: Add Cloud Storage Integration

**Use external storage services:**

#### Amazon S3 (Best for Production)
```python
# After encoding, upload to S3
import boto3
s3 = boto3.client('s3')
s3.upload_file('outputs/720p/video.mp4', 'my-bucket', 'video.mp4')
```

#### Google Cloud Storage
```python
from google.cloud import storage
client = storage.Client()
bucket = client.bucket('my-bucket')
blob = bucket.blob('video.mp4')
blob.upload_from_filename('outputs/720p/video.mp4')
```

#### Cloudflare R2 (S3-compatible, cheaper)
```python
# Use boto3 with R2 endpoint
s3 = boto3.client('s3', endpoint_url='https://xxx.r2.cloudflarestorage.com')
```

**Pros:**
- Files stored permanently
- Accessible from anywhere
- Automatic backups
- CDN delivery

**Cons:**
- Costs money (S3: ~$0.023/GB/month)
- Requires setup

### Option 3: Upgrade Railway Plan

**Railway Pro Plan ($20/month):**
- Persistent volumes available
- More storage space
- Better reliability

---

## Current File Browser Features

### What You Can Do

✅ **View all files** in downloads and outputs folders
```javascript
// Automatic categorization
- Downloads folder (videos, subtitles)
- Outputs folder (organized by resolution)
```

✅ **See file details**
```
- File name
- File size (MB)
- Last modified date/time
- Total storage usage
```

✅ **Download any file**
```
Click "⬇️ Download" button on any file
Direct download via browser
```

✅ **Stream videos**
```
Click "▶️ Stream" button on output videos
Watch in browser without downloading
```

✅ **Real-time updates**
```
Click "🔄 Refresh Files" to see latest files
Updates as jobs complete
```

### What Railway Shows You

When you click "🔄 Refresh Files":

```json
{
  "downloads": [
    {
      "name": "video_20251209_185649.mp4",
      "size_mb": 350.5,
      "modified": "2025-12-09T18:56:49",
      "path": "downloads/video_20251209_185649.mp4"
    }
  ],
  "outputs": {
    "720p": [
      {
        "name": "video_20251209_185649_720p.mp4",
        "size_mb": 100.0,
        "modified": "2025-12-09T19:05:12",
        "path": "outputs/720p/video_20251209_185649_720p.mp4"
      }
    ]
  },
  "total_size_mb": 450.5,
  "total_size_gb": 0.44
}
```

---

## Best Practices for Railway

### 1. Download Files Immediately After Job Completes ⚠️

```
Job Complete ✅
    ↓
Click "⬇️ Download" ASAP
    ↓
Store locally or upload to cloud
    ↓
Files safe from Railway restarts
```

### 2. Monitor Storage Usage

Railway free tier limit: **1GB total storage**

File browser shows:
```
💾 Total Storage: 850 MB (0.83 GB)
⚠️ Only 150 MB remaining before limit!
```

### 3. Clean Up Old Files

After downloading files, you can:
- Manually delete via Railway dashboard (if implemented)
- Let Railway restart clear them automatically
- Current system: Files accumulate until restart

### 4. Use Job Persistence

Current setup saves job metadata to `logs/jobs_state.json`:
```json
{
  "completed_jobs": {
    "job_123": {
      "output_files": {
        "720p": "outputs/720p/video.mp4"
      }
    }
  }
}
```

**This persists across page refresh** (while container is running)
**This is LOST on Railway restart** (ephemeral storage)

---

## Workflow Example

### Production Workflow on Railway

**Step 1: Submit Job**
```
1. Open https://your-app.railway.app
2. Upload subtitle, enter video URL
3. Select "Soft Subtitles" (fast!)
4. Click "Start Processing"
5. See: "✅ Job submitted! You can close this tab"
6. CLOSE BROWSER ✅
```

**Step 2: Check Status (Later)**
```
1. Open https://your-app.railway.app (5-10 min later)
2. See job status:
   - 🔴 JOB RUNNING (50% complete)
   or
   - ✅ Job completed!
```

**Step 3: Download Files**
```
1. Scroll to "📁 File Browser"
2. Click "🔄 Refresh Files"
3. See all outputs:
   - Downloads folder: original files
   - Outputs/720p/: processed video
4. Click "⬇️ Download" on each file
5. Save to your computer
```

**Step 4: Files are Safe**
```
Files now on your computer ✅
Railway can restart safely ✅
Start new job anytime ✅
```

---

## Railway Limitations Summary

| Feature | Railway Free | Local Development |
|---------|--------------|-------------------|
| File access | Web browser only | Direct file access |
| Storage type | Ephemeral | Permanent |
| SSH access | ❌ No | ✅ Yes |
| FTP access | ❌ No | ✅ Yes |
| Persistent storage | ❌ No | ✅ Yes |
| Storage limit | 1GB | Unlimited (disk) |
| Files survive restart | ❌ No | ✅ Yes |
| Download via browser | ✅ Yes | ✅ Yes |

---

## API Endpoints Reference

### Browse Files
```bash
GET /api/files/browse

Response:
{
  "success": true,
  "files": {
    "downloads": [...],
    "outputs": {...},
    "total_size_mb": 450.5
  }
}
```

### Download File
```bash
GET /api/files/download/<path>

Example:
GET /api/files/download/outputs/720p/video.mp4

Response:
Binary file download
```

### Stream Video
```bash
GET /api/stream/<job_id>/<resolution>

Example:
GET /api/stream/20251209_185649_9a1e/720p

Response:
Video stream for browser playback
```

---

## Summary

**Current Setup:**
- ✅ Files stored in Railway container
- ✅ Accessible via web interface File Browser
- ✅ Download anytime via browser
- ✅ Stream videos directly
- ⚠️ Files deleted on Railway restart
- ⚠️ Must download to keep permanently

**Recommendation:**
1. Use **Soft Subtitles** for speed (1 min vs 30 min)
2. **Download files immediately** after job completes
3. Store files on your computer or cloud storage
4. Clean browser cache - Railway handles storage internally

**For Long-term Production:**
- Add S3/R2/GCS integration for permanent storage
- Or upgrade to Railway Pro for persistent volumes
- Current setup works great for temporary processing!
