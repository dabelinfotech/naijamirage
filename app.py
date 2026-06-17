import os
import mimetypes
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, Response, send_file, abort, session)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Vercel has a read-only filesystem except /tmp
_ON_VERCEL = bool(os.environ.get('VERCEL'))
UPLOAD_BASE = '/tmp/uploads'      if _ON_VERCEL else os.path.join(BASE_DIR, 'uploads')
_DB_PATH    = '/tmp/naijamirage.db' if _ON_VERCEL else os.path.join(BASE_DIR, 'naijamirage.db')

# ─── Cloudflare R2 / S3 Storage ───────────────────────────────────────────────

R2_ACCOUNT_ID      = os.environ.get('R2_ACCOUNT_ID', '')
R2_ACCESS_KEY_ID   = os.environ.get('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '')
R2_BUCKET_NAME     = os.environ.get('R2_BUCKET_NAME', 'naijamirage')
USE_R2 = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY)


def _r2():
    import boto3
    from botocore.client import Config
    return boto3.client(
        's3',
        endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto',
    )


def r2_upload(stream, key):
    _r2().upload_fileobj(stream, R2_BUCKET_NAME, key)


def r2_presigned_url(key, download_name=None, expires=3600):
    params = {'Bucket': R2_BUCKET_NAME, 'Key': key}
    if download_name:
        params['ResponseContentDisposition'] = f'attachment; filename="{download_name}"'
    return _r2().generate_presigned_url('get_object', Params=params, ExpiresIn=expires)


def r2_delete(key):
    try:
        _r2().delete_object(Bucket=R2_BUCKET_NAME, Key=key)
    except Exception:
        pass

ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'aac', 'm4a', 'flac'}
ALLOWED_VIDEO = {'mp4', 'webm', 'mkv', 'avi', 'mov'}
ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'naijamirage-Xk9#mP2$vR7@qL5!')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _ON_VERCEL  # HTTPS only on Vercel

# ─── Admin credentials (set ADMIN_USERNAME / ADMIN_PASSWORD in env for prod) ──
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'naijadmin')
_raw_pw        = os.environ.get('ADMIN_PASSWORD', 'NaijaMirage@2025!')
ADMIN_PASSWORD_HASH = generate_password_hash(_raw_pw)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login', next=request.path))
        return f(*args, **kwargs)
    return decorated

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{_DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

db = SQLAlchemy(app)


# ─── Models ───────────────────────────────────────────────────────────────────

class NewsArticle(db.Model):
    __tablename__ = 'news_articles'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), default='General')
    image_path = db.Column(db.String(500))
    author = db.Column(db.String(150), default='Naijamirage Staff')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AudioTrack(db.Model):
    __tablename__ = 'audio_tracks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    genre = db.Column(db.String(100), default='Afrobeats')
    file_path = db.Column(db.String(500), nullable=False)
    cover_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer, default=0)
    download_count = db.Column(db.Integer, default=0)
    play_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MusicVideo(db.Model):
    __tablename__ = 'music_videos'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    genre = db.Column(db.String(100), default='Afrobeats')
    file_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer, default=0)
    download_count = db.Column(db.Integer, default=0)
    play_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set


def save_upload(file, subfolder, allowed_set):
    """Save uploaded file to R2 or local disk; return filename or None."""
    if not file or file.filename == '':
        return None
    if not allowed_file(file.filename, allowed_set):
        return None
    filename = secure_filename(file.filename)
    base, ext = os.path.splitext(filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    filename = f"{base}_{timestamp}{ext}"
    if USE_R2:
        file.stream.seek(0)
        r2_upload(file.stream, f"{subfolder}/{filename}")
    else:
        dest = os.path.join(UPLOAD_BASE, subfolder, filename)
        file.save(dest)
    return filename


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024**2):.1f} MB"
    return f"{size_bytes / (1024**3):.2f} GB"


app.jinja_env.filters['filesize'] = format_size

from urllib.parse import quote_plus
app.jinja_env.filters['urlencode'] = quote_plus


def stream_file(filepath, mimetype=None):
    """Stream a file with HTTP range-request support."""
    if not os.path.isfile(filepath):
        abort(404)
    file_size = os.path.getsize(filepath)
    if mimetype is None:
        mimetype, _ = mimetypes.guess_type(filepath)
        mimetype = mimetype or 'application/octet-stream'

    range_header = request.headers.get('Range')
    if range_header:
        try:
            ranges = range_header.strip().replace('bytes=', '')
            start_str, end_str = ranges.split('-')
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
        except (ValueError, AttributeError):
            abort(416)

        end = min(end, file_size - 1)
        length = end - start + 1

        def generate():
            with open(filepath, 'rb') as f:
                f.seek(start)
                remaining = length
                chunk = 65536
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Type': mimetype,
        }
        return Response(generate(), status=206, headers=headers)

    # No Range header — serve the whole file
    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Length': str(file_size),
        'Content-Type': mimetype,
    }
    def generate_full():
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                yield data
    return Response(generate_full(), status=200, headers=headers)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    articles = NewsArticle.query.order_by(NewsArticle.created_at.desc()).limit(6).all()
    audio_tracks = AudioTrack.query.order_by(AudioTrack.created_at.desc()).limit(4).all()
    music_videos = MusicVideo.query.order_by(MusicVideo.created_at.desc()).limit(4).all()
    entertainment = NewsArticle.query.filter_by(category='Entertainment')\
        .order_by(NewsArticle.created_at.desc()).limit(3).all()
    return render_template('index.html', articles=articles,
                           audio_tracks=audio_tracks,
                           music_videos=music_videos,
                           entertainment=entertainment)


@app.route('/news')
def news():
    category = request.args.get('category', '')
    search_q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    query = NewsArticle.query
    if category:
        query = query.filter_by(category=category)
    if search_q:
        like = f'%{search_q}%'
        query = query.filter(
            db.or_(
                NewsArticle.title.ilike(like),
                NewsArticle.summary.ilike(like),
                NewsArticle.content.ilike(like),
                NewsArticle.author.ilike(like),
            )
        )
    articles = query.order_by(NewsArticle.created_at.desc()).paginate(
        page=page, per_page=12, error_out=False)
    categories = db.session.query(NewsArticle.category).distinct().all()
    categories = [c[0] for c in categories]
    return render_template('news.html', articles=articles,
                           categories=categories, selected_category=category,
                           search_q=search_q)


@app.route('/news/<int:article_id>')
def article(article_id):
    art = NewsArticle.query.get_or_404(article_id)
    related = NewsArticle.query.filter(
        NewsArticle.category == art.category,
        NewsArticle.id != art.id
    ).order_by(NewsArticle.created_at.desc()).limit(4).all()
    return render_template('article.html', article=art, related=related)


@app.route('/entertainment')
def entertainment():
    articles = NewsArticle.query.filter(
        NewsArticle.category.in_(['Entertainment', 'Celebrity', 'Lifestyle', 'Culture'])
    ).order_by(NewsArticle.created_at.desc()).all()
    return render_template('entertainment.html', articles=articles)


@app.route('/music')
def music():
    genre = request.args.get('genre', '')
    page = request.args.get('page', 1, type=int)
    query = AudioTrack.query
    if genre:
        query = query.filter_by(genre=genre)
    tracks = query.order_by(AudioTrack.created_at.desc()).paginate(
        page=page, per_page=12, error_out=False)
    genres = db.session.query(AudioTrack.genre).distinct().all()
    genres = [g[0] for g in genres]
    return render_template('music.html', tracks=tracks,
                           genres=genres, selected_genre=genre)


@app.route('/videos')
def videos():
    genre = request.args.get('genre', '')
    page = request.args.get('page', 1, type=int)
    query = MusicVideo.query
    if genre:
        query = query.filter_by(genre=genre)
    vids = query.order_by(MusicVideo.created_at.desc()).paginate(
        page=page, per_page=12, error_out=False)
    genres = db.session.query(MusicVideo.genre).distinct().all()
    genres = [g[0] for g in genres]
    return render_template('videos.html', videos=vids,
                           genres=genres, selected_genre=genre)


@app.route('/upload', methods=['GET'])
@login_required
def upload():
    return render_template('upload.html')


@app.route('/upload/news', methods=['POST'])
@login_required
def upload_news():
    title = request.form.get('title', '').strip()
    summary = request.form.get('summary', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', 'General').strip()
    author = request.form.get('author', 'Naijamirage Staff').strip()

    if not title or not content:
        flash('Title and content are required.', 'error')
        return redirect(url_for('upload'))

    image_filename = None
    if 'image' in request.files:
        image_filename = save_upload(request.files['image'], 'news_images', ALLOWED_IMAGE)

    article = NewsArticle(
        title=title, summary=summary or content[:200],
        content=content, category=category,
        author=author, image_path=image_filename
    )
    db.session.add(article)
    db.session.commit()
    flash('News article published successfully!', 'success')
    return redirect(url_for('news'))


@app.route('/upload/audio', methods=['POST'])
@login_required
def upload_audio():
    title = request.form.get('title', '').strip()
    artist = request.form.get('artist', '').strip()
    description = request.form.get('description', '').strip()
    genre = request.form.get('genre', 'Afrobeats').strip()

    if not title or not artist:
        flash('Title and artist are required.', 'error')
        return redirect(url_for('upload'))

    if 'audio_file' not in request.files:
        flash('No audio file selected.', 'error')
        return redirect(url_for('upload'))

    audio_file = request.files['audio_file']
    audio_file.stream.seek(0, 2)
    file_size = audio_file.stream.tell()
    audio_file.stream.seek(0)

    audio_filename = save_upload(audio_file, 'audio', ALLOWED_AUDIO)
    if not audio_filename:
        flash('Invalid audio file. Allowed: mp3, wav, ogg, aac, m4a, flac', 'error')
        return redirect(url_for('upload'))

    cover_filename = None
    if 'cover_image' in request.files:
        cover_filename = save_upload(request.files['cover_image'], 'covers', ALLOWED_IMAGE)
    track = AudioTrack(
        title=title, artist=artist, description=description,
        genre=genre, file_path=audio_filename,
        cover_path=cover_filename, file_size=file_size
    )
    db.session.add(track)
    db.session.commit()
    flash('Audio track uploaded successfully!', 'success')
    return redirect(url_for('music'))


@app.route('/upload/video', methods=['POST'])
@login_required
def upload_video():
    title = request.form.get('title', '').strip()
    artist = request.form.get('artist', '').strip()
    description = request.form.get('description', '').strip()
    genre = request.form.get('genre', 'Afrobeats').strip()

    if not title or not artist:
        flash('Title and artist are required.', 'error')
        return redirect(url_for('upload'))

    if 'video_file' not in request.files:
        flash('No video file selected.', 'error')
        return redirect(url_for('upload'))

    video_file = request.files['video_file']
    video_file.stream.seek(0, 2)
    file_size = video_file.stream.tell()
    video_file.stream.seek(0)

    video_filename = save_upload(video_file, 'videos', ALLOWED_VIDEO)
    if not video_filename:
        flash('Invalid video file. Allowed: mp4, webm, mkv, avi, mov', 'error')
        return redirect(url_for('upload'))

    thumb_filename = None
    if 'thumbnail' in request.files:
        thumb_filename = save_upload(request.files['thumbnail'], 'thumbnails', ALLOWED_IMAGE)
    video = MusicVideo(
        title=title, artist=artist, description=description,
        genre=genre, file_path=video_filename,
        thumbnail_path=thumb_filename, file_size=file_size
    )
    db.session.add(video)
    db.session.commit()
    flash('Music video uploaded successfully!', 'success')
    return redirect(url_for('videos'))


# ─── Streaming ────────────────────────────────────────────────────────────────

@app.route('/stream/audio/<int:track_id>')
def stream_audio(track_id):
    track = AudioTrack.query.get_or_404(track_id)
    track.play_count += 1
    db.session.commit()
    if USE_R2:
        return redirect(r2_presigned_url(f"audio/{track.file_path}"))
    filepath = os.path.join(UPLOAD_BASE, 'audio', track.file_path)
    return stream_file(filepath)


@app.route('/stream/video/<int:video_id>')
def stream_video(video_id):
    video = MusicVideo.query.get_or_404(video_id)
    video.play_count += 1
    db.session.commit()
    if USE_R2:
        return redirect(r2_presigned_url(f"videos/{video.file_path}"))
    filepath = os.path.join(UPLOAD_BASE, 'videos', video.file_path)
    return stream_file(filepath)


# ─── Downloads ────────────────────────────────────────────────────────────────

@app.route('/download/audio/<int:track_id>')
def download_audio(track_id):
    track = AudioTrack.query.get_or_404(track_id)
    track.download_count += 1
    db.session.commit()
    download_name = secure_filename(f"{track.artist} - {track.title}{os.path.splitext(track.file_path)[1]}")
    if USE_R2:
        return redirect(r2_presigned_url(f"audio/{track.file_path}", download_name=download_name))
    filepath = os.path.join(UPLOAD_BASE, 'audio', track.file_path)
    if not os.path.isfile(filepath):
        abort(404)
    return send_file(filepath, as_attachment=True, download_name=download_name)


@app.route('/download/video/<int:video_id>')
def download_video(video_id):
    video = MusicVideo.query.get_or_404(video_id)
    video.download_count += 1
    db.session.commit()
    download_name = secure_filename(f"{video.artist} - {video.title}{os.path.splitext(video.file_path)[1]}")
    if USE_R2:
        return redirect(r2_presigned_url(f"videos/{video.file_path}", download_name=download_name))
    filepath = os.path.join(UPLOAD_BASE, 'videos', video.file_path)
    if not os.path.isfile(filepath):
        abort(404)
    return send_file(filepath, as_attachment=True, download_name=download_name)


# ─── Media file serving ───────────────────────────────────────────────────────

@app.route('/media/covers/<path:filename>')
def serve_cover(filename):
    if USE_R2:
        return redirect(r2_presigned_url(f"covers/{filename}"))
    return send_file(os.path.join(UPLOAD_BASE, 'covers', filename))


@app.route('/media/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    if USE_R2:
        return redirect(r2_presigned_url(f"thumbnails/{filename}"))
    return send_file(os.path.join(UPLOAD_BASE, 'thumbnails', filename))


@app.route('/media/news_images/<path:filename>')
def serve_news_image(filename):
    if USE_R2:
        return redirect(r2_presigned_url(f"news_images/{filename}"))
    return send_file(os.path.join(UPLOAD_BASE, 'news_images', filename))


# ─── Admin: helpers ───────────────────────────────────────────────────────────

def delete_file(subfolder, filename):
    """Silently remove a file from R2 or local uploads subfolder."""
    if not filename:
        return
    if USE_R2:
        r2_delete(f"{subfolder}/{filename}")
    else:
        try:
            os.remove(os.path.join(UPLOAD_BASE, subfolder, filename))
        except OSError:
            pass


# ─── Admin: login / logout ────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session['admin_logged_in'] = True
            session.modified = True
            next_url = request.args.get('next') or url_for('admin_dashboard')
            resp = redirect(next_url)
            return resp
        flash('Invalid username or password.', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


# ─── Admin: dashboard ─────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin_dashboard():
    articles = NewsArticle.query.order_by(NewsArticle.created_at.desc()).all()
    tracks   = AudioTrack.query.order_by(AudioTrack.created_at.desc()).all()
    vids     = MusicVideo.query.order_by(MusicVideo.created_at.desc()).all()
    return render_template('admin.html',
                           articles=articles, tracks=tracks, videos=vids)


# ─── Admin: news ──────────────────────────────────────────────────────────────

@app.route('/admin/news/<int:article_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_news(article_id):
    art = NewsArticle.query.get_or_404(article_id)
    if request.method == 'POST':
        art.title    = request.form.get('title', art.title).strip()
        art.summary  = request.form.get('summary', art.summary).strip()
        art.content  = request.form.get('content', art.content).strip()
        art.category = request.form.get('category', art.category).strip()
        art.author   = request.form.get('author', art.author).strip()

        if 'image' in request.files and request.files['image'].filename:
            new_img = save_upload(request.files['image'], 'news_images', ALLOWED_IMAGE)
            if new_img:
                delete_file('news_images', art.image_path)
                art.image_path = new_img

        db.session.commit()
        flash(f'Article "{art.title}" updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_news.html', article=art)


@app.route('/admin/news/<int:article_id>/delete', methods=['POST'])
@login_required
def admin_delete_news(article_id):
    art = NewsArticle.query.get_or_404(article_id)
    title = art.title
    delete_file('news_images', art.image_path)
    db.session.delete(art)
    db.session.commit()
    flash(f'Article "{title}" deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# ─── Admin: audio ─────────────────────────────────────────────────────────────

@app.route('/admin/audio/<int:track_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_audio(track_id):
    track = AudioTrack.query.get_or_404(track_id)
    if request.method == 'POST':
        track.title       = request.form.get('title', track.title).strip()
        track.artist      = request.form.get('artist', track.artist).strip()
        track.genre       = request.form.get('genre', track.genre).strip()
        track.description = request.form.get('description', track.description or '').strip()

        if 'audio_file' in request.files and request.files['audio_file'].filename:
            af = request.files['audio_file']
            af.stream.seek(0, 2)
            new_size = af.stream.tell()
            af.stream.seek(0)
            new_audio = save_upload(af, 'audio', ALLOWED_AUDIO)
            if new_audio:
                delete_file('audio', track.file_path)
                track.file_path = new_audio
                track.file_size = new_size

        if 'cover_image' in request.files and request.files['cover_image'].filename:
            new_cover = save_upload(request.files['cover_image'], 'covers', ALLOWED_IMAGE)
            if new_cover:
                delete_file('covers', track.cover_path)
                track.cover_path = new_cover

        db.session.commit()
        flash(f'Track "{track.title}" updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_audio.html', track=track)


@app.route('/admin/audio/<int:track_id>/delete', methods=['POST'])
@login_required
def admin_delete_audio(track_id):
    track = AudioTrack.query.get_or_404(track_id)
    title = track.title
    delete_file('audio', track.file_path)
    delete_file('covers', track.cover_path)
    db.session.delete(track)
    db.session.commit()
    flash(f'Track "{title}" deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# ─── Admin: video ─────────────────────────────────────────────────────────────

@app.route('/admin/video/<int:video_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_video(video_id):
    video = MusicVideo.query.get_or_404(video_id)
    if request.method == 'POST':
        video.title       = request.form.get('title', video.title).strip()
        video.artist      = request.form.get('artist', video.artist).strip()
        video.genre       = request.form.get('genre', video.genre).strip()
        video.description = request.form.get('description', video.description or '').strip()

        if 'video_file' in request.files and request.files['video_file'].filename:
            vf = request.files['video_file']
            vf.stream.seek(0, 2)
            new_size = vf.stream.tell()
            vf.stream.seek(0)
            new_vid = save_upload(vf, 'videos', ALLOWED_VIDEO)
            if new_vid:
                delete_file('videos', video.file_path)
                video.file_path = new_vid
                video.file_size = new_size

        if 'thumbnail' in request.files and request.files['thumbnail'].filename:
            new_thumb = save_upload(request.files['thumbnail'], 'thumbnails', ALLOWED_IMAGE)
            if new_thumb:
                delete_file('thumbnails', video.thumbnail_path)
                video.thumbnail_path = new_thumb

        db.session.commit()
        flash(f'Video "{video.title}" updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_video.html', video=video)


@app.route('/admin/video/<int:video_id>/delete', methods=['POST'])
@login_required
def admin_delete_video(video_id):
    video = MusicVideo.query.get_or_404(video_id)
    title = video.title
    delete_file('videos', video.file_path)
    delete_file('thumbnails', video.thumbnail_path)
    db.session.delete(video)
    db.session.commit()
    flash(f'Video "{title}" deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# ─── Init & Run ───────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # Ensure upload directories exist
    for sub in ('audio', 'videos', 'covers', 'thumbnails', 'news_images'):
        os.makedirs(os.path.join(UPLOAD_BASE, sub), exist_ok=True)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
