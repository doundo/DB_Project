import functools
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, jsonify
import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash, generate_password_hash

from config import DB_CONFIG

app = Flask(__name__)
# 세션 사용을 위한 시크릿 키 설정
app.secret_key = 'dev'

# DB 연결 (g 객체를 사용하여 요청 내에서 재사용)
def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG, cursorclass=DictCursor)
    return g.db

# 각 요청이 끝난 후 DB 연결을 닫는 함수
@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# 모든 요청 전에 실행되어 로그인된 사용자 정보를 로드
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        g.user = cur.fetchone()

# 로그인이 필요한 라우트를 위한 데코레이터
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def get_notes_with_hashtags(entity_type, entity_id):
    """지정된 엔티티(노래, 아티스트, 앨범)에 대한 노트와 해시태그를 가져옵니다."""
    db = get_db()
    cur = db.cursor()
    sql_notes = """
        SELECT n.id, n.note, n.created_at, u.user_name, GROUP_CONCAT(h.content SEPARATOR ', ') as hashtags
        FROM notes n
        JOIN users u ON n.user_id = u.id
        LEFT JOIN hashtag_notes hn ON n.id = hn.note_id
        LEFT JOIN hashtags h ON hn.hashtag_id = h.id
        WHERE n.entity_type = %s AND n.entity_id = %s
        GROUP BY n.id
        ORDER BY n.created_at DESC
    """
    cur.execute(sql_notes, (entity_type, entity_id))
    return cur.fetchall()

# 1. 메인 페이지: 노래 목록
@app.route('/')
def index():
    db = get_db()
    cur = db.cursor()
    sql = """
        SELECT s.id, s.song_name, a.artist_name, al.album_name, a.id as artist_id, al.id as album_id
        FROM songs s
        JOIN artists a ON s.artist_id = a.id
        JOIN albums al ON s.album_id = al.id
        ORDER BY s.id DESC
    """
    cur.execute(sql)
    song_list = cur.fetchall()
    return render_template('songlist.html', song_list=song_list)

# 2. 상세 페이지 (노트/해시태그 포함)
@app.route('/view')
def view_song():
    song_id = request.args.get('id')
    db = get_db()
    cur = db.cursor()
    
    # 노래 상세 정보
    sql_song = """
        SELECT s.id, s.song_name, a.artist_name, al.album_name, al.release_date, s.release_date as song_release_date, a.id as artist_id, al.id as album_id
        FROM songs s
        JOIN artists a ON s.artist_id = a.id
        JOIN albums al ON s.album_id = al.id
        WHERE s.id = %s
    """
    cur.execute(sql_song, (song_id,))
    song = cur.fetchone()
    
    # 404 Not Found 처리
    if song is None:
        return "Song not found", 404
    
    # 아티스트 통계
    artist_id = song['artist_id']
    cur.callproc('GetArtistStats', (artist_id,))
    stats = cur.fetchone()

    # 노트 및 해시태그 정보
    notes_with_hashtags = get_notes_with_hashtags('song', song_id)
    
    return render_template('songview.html', song=song, stats=stats, notes_with_hashtags=notes_with_hashtags)

# 2-1. 아티스트 상세 페이지
@app.route('/artist/<int:artist_id>')
def view_artist(artist_id):
    db = get_db()
    cur = db.cursor()

    # 아티스트 정보
    cur.execute("SELECT * FROM artists WHERE id = %s", (artist_id,))
    artist = cur.fetchone()

    # 아티스트의 노래 목록
    sql_songs = """
        SELECT s.id, s.song_name, al.album_name, al.id as album_id
        FROM songs s
        JOIN albums al ON s.album_id = al.id
        WHERE s.artist_id = %s
        ORDER BY al.release_date DESC, s.song_name
    """
    cur.execute(sql_songs, (artist_id,))
    songs = cur.fetchall()

    # 노트 및 해시태그 정보
    notes_with_hashtags = get_notes_with_hashtags('artist', artist_id)

    return render_template('artist_view.html', artist=artist, songs=songs, notes_with_hashtags=notes_with_hashtags)

# 2-2. 앨범 상세 페이지
@app.route('/album/<int:album_id>')
def view_album(album_id):
    db = get_db()
    cur = db.cursor()

    # 앨범 정보 (아티스트 이름 포함)
    sql_album = """
        SELECT al.id, al.album_name, al.release_date, al.artist_id, a.artist_name
        FROM albums al
        JOIN artists a ON al.artist_id = a.id
        WHERE al.id = %s
    """
    cur.execute(sql_album, (album_id,))
    album = cur.fetchone()

    # 앨범의 노래 목록
    cur.execute("SELECT id, song_name FROM songs WHERE album_id = %s ORDER BY song_name", (album_id,))
    songs = cur.fetchall()

    # 노트 및 해시태그 정보
    notes_with_hashtags = get_notes_with_hashtags('album', album_id)

    return render_template('album_view.html', album=album, songs=songs, notes_with_hashtags=notes_with_hashtags)

# 3. 평점 등록
@app.route('/rate', methods=['POST'])
@login_required
def rate_song():
    song_id = request.form['song_id']
    score = request.form['score']
    review = request.form['review']
    
    db = get_db()
    cur = db.cursor()
    cur.callproc('UpsertSongRating', (g.user['id'], song_id, score, review))
    db.commit()
    
    return redirect(url_for('view_song', id=song_id))

# 4. 아티스트 추가
@app.route('/add-artist', methods=['GET', 'POST'])
@login_required
def add_artist():
    if request.method == 'POST':
        artist_name = request.form['artist_name']
        info = request.form.get('info', '')
        
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("INSERT INTO artists (artist_name, info) VALUES (%s, %s)", (artist_name, info))
            db.commit()
            flash(f"아티스트 '{artist_name}'이(가) 성공적으로 추가되었습니다.")
            return redirect(url_for('index'))
        except pymysql.err.IntegrityError:
            flash(f"오류: 아티스트 '{artist_name}'은(는) 이미 존재합니다.")
            return redirect(url_for('add_artist'))

    return render_template('add_artist.html')

# 5. 앨범 추가
@app.route('/add-album', methods=['GET', 'POST'])
@login_required
def add_album():
    if request.method == 'POST':
        artist_id = request.form['artist_id']
        album_name = request.form['album_name']
        release_date = request.form.get('release_date') or None
        
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("INSERT INTO albums (album_name, artist_id, release_date) VALUES (%s, %s, %s)", (album_name, artist_id, release_date))
            db.commit()
            flash(f"앨범 '{album_name}'이(가) 성공적으로 추가되었습니다.")
            return redirect(url_for('index'))
        except pymysql.err.IntegrityError:
            flash(f"오류: 해당 아티스트의 앨범 '{album_name}'은(는) 이미 존재합니다.")
            return redirect(url_for('add_album'))

    return render_template('add_album.html')

# 6. 노래 추가
@app.route('/add-song', methods=['GET', 'POST'])
@login_required
def add_song():
    if request.method == 'POST':
        song_name = request.form['song_name']
        artist_id = request.form['artist_id']
        album_id = request.form['album_id']
        release_date = request.form.get('release_date') or None
        
        try:
            db = get_db()
            cur = db.cursor()
            
            # 1. 노래 추가
            sql = "INSERT INTO songs (song_name, artist_id, album_id, release_date) VALUES (%s, %s, %s, %s)"
            cur.execute(sql, (song_name, artist_id, album_id, release_date))
            
            # 2. (선택) 평점 추가
            score = request.form.get('score')
            if score:
                new_song_id = cur.lastrowid
                review = request.form.get('review', '')
                cur.callproc('UpsertSongRating', (g.user['id'], new_song_id, score, review))

            db.commit()
            flash(f"노래 '{song_name}'이(가) 성공적으로 추가되었습니다.")
            return redirect(url_for('index'))

        except pymysql.err.IntegrityError:
            flash(f"오류: 해당 아티스트의 노래 '{song_name}'은(는) 이미 존재합니다.")
            return redirect(url_for('add_song'))

    return render_template('add_song.html')

@app.route('/add-note-flow')
@login_required
def add_note_flow():
    return render_template('add_note_flow.html')

def _process_hashtags(cur, note_id, hashtags_str):
    """Parses a string of hashtags, creates new ones if necessary, and links them to a note."""
    if not hashtags_str:
        return

    tags = [tag.strip().lstrip('#') for tag in hashtags_str.split(',') if tag.strip()]
    for tag in tags:
        # Find hashtag or create it
        cur.execute("SELECT id FROM hashtags WHERE content = %s", (tag,))
        hashtag = cur.fetchone()
        if hashtag:
            hashtag_id = hashtag['id']
        else:
            cur.execute("INSERT INTO hashtags (content) VALUES (%s)", (tag,))
            hashtag_id = cur.lastrowid
        
        # Link hashtag to the note, ignoring duplicates
        cur.execute(
            "INSERT IGNORE INTO hashtag_notes (note_id, hashtag_id) VALUES (%s, %s)",
            (note_id, hashtag_id)
        )

# 6-1. 노트/해시태그 추가
@app.route('/add-note/<string:entity_type>/<int:entity_id>', methods=['GET', 'POST'])
@login_required
def add_note(entity_type, entity_id):
    if request.method == 'POST':
        note_content = request.form['note']
        hashtags_str = request.form.get('hashtags', '')

        db = get_db()
        cur = db.cursor()

        try:
            # 1. 노트 추가
            sql_add_note = "INSERT INTO notes (entity_id, entity_type, note, user_id) VALUES (%s, %s, %s, %s)"
            cur.execute(sql_add_note, (entity_id, entity_type, note_content, g.user['id']))
            new_note_id = cur.lastrowid

            # 2. 해시태그 처리
            _process_hashtags(cur, new_note_id, hashtags_str)
            
            db.commit()

        except Exception as e:
            db.rollback()
            flash(f"An error occurred: {e}")
        
        # 엔티티 타입에 따라 적절한 뷰로 리디렉션
        if entity_type == 'song':
            return redirect(url_for('view_song', id=entity_id))
        elif entity_type == 'artist':
            return redirect(url_for('view_artist', artist_id=entity_id))
        elif entity_type == 'album':
            return redirect(url_for('view_album', album_id=entity_id))
        else:
            return redirect(url_for('index'))

    return render_template('add_note.html', entity_type=entity_type, entity_id=entity_id)

# 7. 회원가입
@app.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cur = db.cursor()
        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        
        if error is None:
            try:
                cur.execute(
                    "INSERT INTO users (user_name, password) VALUES (%s, %s)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
            except pymysql.err.IntegrityError:
                error = f"User {username} is already registered."
            else:
                return redirect(url_for("login"))
        
        flash(error)

    return render_template('register.html')

# 8. 로그인
@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cur = db.cursor()
        error = None
        cur.execute("SELECT * FROM users WHERE user_name = %s", (username,))
        user = cur.fetchone()

        if user is None:
            error = 'Incorrect username.'
        elif not check_password_hash(user['password'], password):
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('index'))

        flash(error)

    return render_template('login.html')

# 9. 로그아웃
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 10. 프로필 페이지
@app.route('/profile')
@login_required
def profile():
    db = get_db()
    cur = db.cursor()
    
    # GetUserActivity 프로시저 호출
    user_id = g.user['id']
    cur.callproc('GetUserActivity', (user_id,))
    activity = cur.fetchone()
    
    return render_template('profile.html', activity=activity)

# 11. 차트 페이지
@app.route('/charts')
def charts():
    db = get_db()
    cur = db.cursor()

    # Top 10 Rated Songs
    cur.callproc('GetTopRatedSongs', (10,))
    top_songs = cur.fetchall()

    # Top 10 Most Rated Artists
    cur.callproc('GetMostRatedArtists', (10,))
    top_artists = cur.fetchall()

    return render_template('charts.html', top_songs=top_songs, top_artists=top_artists)

# --- API Endpoints for Search ---
def _api_search(sql, use_proc=False):
    """Helper function for API search endpoints."""
    query = request.args.get('q', '')
    if not query:
        return jsonify([])

    db = get_db()
    cur = db.cursor()
    
    like_query = f"%{query}%"
    
    if use_proc:
        # Assumes procedure signature is (query, limit)
        cur.callproc(sql, (like_query, 10))
    else:
        cur.execute(sql, (like_query,))
        
    results = cur.fetchall()
    return jsonify(results)

@app.route('/api/search/artists')
@login_required
def search_artists():
    sql = "SELECT id, artist_name as text FROM artists WHERE artist_name LIKE %s LIMIT 10"
    return _api_search(sql)

@app.route('/api/search/albums')
@login_required
def search_albums():
    artist_id = request.args.get('artist_id', None)
    query = request.args.get('q', '')
    
    db = get_db()
    cur = db.cursor()

    sql = "SELECT id, album_name as text FROM albums WHERE album_name LIKE %s"
    params = [f"%{query}%"]

    if artist_id:
        sql += " AND artist_id = %s"
        params.append(artist_id)
    
    sql += " LIMIT 10"

    cur.execute(sql, tuple(params))
    results = cur.fetchall()
    return jsonify(results)

@app.route('/api/search/songs')
@login_required
def search_songs():
    sql = "SELECT s.id, CONCAT(s.song_name, ' - ', a.artist_name) as text FROM songs s JOIN artists a ON s.artist_id = a.id WHERE s.song_name LIKE %s LIMIT 10"
    return _api_search(sql)

@app.route('/api/search/hashtags')
@login_required
def search_hashtags():
    return _api_search('SearchHashtags', use_proc=True)

@app.route('/hashtag/<string:hashtag_name>')
def view_hashtag(hashtag_name):
    db = get_db()
    cur = db.cursor()

    # Get songs for the hashtag
    cur.callproc('GetSongsByHashtag', (hashtag_name,))
    songs = cur.fetchall()
    
    return render_template('hashtag_view.html', hashtag_name=hashtag_name, songs=songs)



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)