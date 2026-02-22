import pymysql
from pymysql.cursors import DictCursor
from config import DB_CONFIG

try:
    # 'with' 구문을 사용하여 연결 및 커서 리소스를 자동으로 관리
    with pymysql.connect(**DB_CONFIG, cursorclass=DictCursor) as conn:
        with conn.cursor() as cursor:
            # JOIN 쿼리로 노래 정보 가져오기
            sql = """
                SELECT s.id, s.song_name, a.artist_name, al.album_name 
                FROM songs s
                JOIN artists a ON s.artist_id = a.id
                JOIN albums al ON s.album_id = al.id
                ORDER BY s.id
            """
            cursor.execute(sql)
            data = cursor.fetchall()

    # 결과 출력 (DictCursor 사용)
    print(f"{'ID':<5} {'SONG':<20} {'ARTIST':<15} {'ALBUM':<20}")
    print("-" * 60)
    if data:
        for row in data:
            print(f"{row['id']:<5} {row['song_name']:<20} {row['artist_name']:<15} {row['album_name']:<20}")

except pymysql.Error as e:
    print(f"데이터베이스 오류가 발생했습니다: {e}")