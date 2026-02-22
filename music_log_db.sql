-- [1] 데이터베이스 생성 및 선택
CREATE DATABASE IF NOT EXISTS music_log_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE music_log_db;
SET NAMES 'utf8mb4';

-- 외래 키 관계 순서와 상관없이 테이블을 초기화하기 위해 체크 해제
SET FOREIGN_KEY_CHECKS = 0;

-- [2] 기존 테이블 초기화
DROP TABLE IF EXISTS hashtag_notes;
DROP TABLE IF EXISTS hashtags;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS rates;
DROP TABLE IF EXISTS songs;
DROP TABLE IF EXISTS albums;
DROP TABLE IF EXISTS artists;
DROP TABLE IF EXISTS users;

-- [3] 테이블 생성
-- 1. Users
CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_name VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL
);

-- 2. Artists
CREATE TABLE artists (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    artist_name VARCHAR(255) NOT NULL UNIQUE,
    info TEXT NULL
);

-- 3. Albums
CREATE TABLE albums (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    album_name VARCHAR(255) NOT NULL,
    artist_id BIGINT NOT NULL,
    release_date DATE NULL,
    FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE,
    UNIQUE KEY uk_album_artist (album_name, artist_id)
);

-- 4. Songs
CREATE TABLE songs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    song_name VARCHAR(255) NOT NULL,
    artist_id BIGINT NOT NULL,
    album_id BIGINT NULL,
    release_date DATE NULL,
    FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE,
    FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
    UNIQUE KEY uk_song_artist (song_name, artist_id)
);

-- 5. Rates
CREATE TABLE rates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    song_id BIGINT NOT NULL,
    score INT NOT NULL CHECK (score BETWEEN 1 AND 5),
    review TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    user_id BIGINT NOT NULL,
    FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uk_user_song_rate (user_id, song_id)
);

-- 6. Notes
CREATE TABLE notes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity_id BIGINT NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    note TEXT NOT NULL,
    public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    user_id BIGINT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_notes_entity (entity_id, entity_type)
);

-- 7. Hashtags
CREATE TABLE hashtags (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    content VARCHAR(100) NOT NULL UNIQUE
);

-- 8. Hashtag_Notes
CREATE TABLE hashtag_notes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    note_id BIGINT NOT NULL,
    hashtag_id BIGINT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (hashtag_id) REFERENCES hashtags(id) ON DELETE CASCADE,
    UNIQUE KEY uk_note_hashtag (note_id, hashtag_id)
);

-- 외래 키 체크 다시 활성화
SET FOREIGN_KEY_CHECKS = 1;

-- [4] 더미 데이터 입력
INSERT INTO users (user_name, password) VALUES ('root', 'root');
INSERT INTO artists (artist_name, info) VALUES ('마이클 잭슨', '팝의 황제'), ('위켄드', '');
INSERT INTO albums (album_name, artist_id, release_date) VALUES ('Off the Wall', 1, '1979-08-10'), ('After Hours', 2, '2020-03-20');
INSERT INTO songs (song_name, album_id, artist_id) VALUES ('Don''t Stop ''Til You Get Enough', 1, 1), ('Rock With You', 1, 1), ('Blinding Lights', 2, 2);

-- [5] 프로시저 생성 (테이블 생성 후 실행해야 안전함)
DELIMITER //

-- 1. 평점 등록/수정 (Upsert)
DROP PROCEDURE IF EXISTS UpsertSongRating//
CREATE PROCEDURE UpsertSongRating(
    IN p_user_id BIGINT,
    IN p_song_id BIGINT,
    IN p_score INT,
    IN p_review TEXT
)
BEGIN
    INSERT INTO rates (user_id, song_id, score, review) 
    VALUES (p_user_id, p_song_id, p_score, p_review)
    ON DUPLICATE KEY UPDATE 
        score = p_score, 
        review = p_review, 
        last_update_at = NOW();
END //

-- 2. 아티스트 통계 (Stats)
DROP PROCEDURE IF EXISTS GetArtistStats//
CREATE PROCEDURE GetArtistStats(
    IN p_artist_id BIGINT
)
BEGIN
    SELECT 
        (SELECT COUNT(*) FROM songs WHERE artist_id = p_artist_id) AS p_song_count,
        (SELECT IFNULL(AVG(r.score), 0.0) FROM rates r JOIN songs s ON r.song_id = s.id WHERE s.artist_id = p_artist_id) AS p_avg_score;
END //

-- 3. 사용자 활동 통계
DROP PROCEDURE IF EXISTS GetUserActivity//
CREATE PROCEDURE GetUserActivity(
    IN p_user_id BIGINT
)
BEGIN
    SELECT 
        (SELECT COUNT(*) FROM rates WHERE user_id = p_user_id) AS p_total_ratings,
        (SELECT IFNULL(AVG(score), 0.0) FROM rates WHERE user_id = p_user_id) AS p_avg_score,
        (SELECT s.id FROM rates r JOIN songs s ON r.song_id = s.id WHERE r.user_id = p_user_id ORDER BY r.last_update_at DESC LIMIT 1) AS p_last_rated_song_id,
        (SELECT s.song_name FROM rates r JOIN songs s ON r.song_id = s.id WHERE r.user_id = p_user_id ORDER BY r.last_update_at DESC LIMIT 1) AS p_last_rated_song_name;
END //

-- 4. Top N 노래 (평점순)
DROP PROCEDURE IF EXISTS GetTopRatedSongs//
CREATE PROCEDURE GetTopRatedSongs(
    IN p_limit INT
)
BEGIN
    SELECT 
        s.id,
        s.song_name,
        a.artist_name,
        a.id as artist_id,
        AVG(r.score) as avg_score,
        COUNT(r.id) as rating_count
    FROM songs s
    JOIN rates r ON s.id = r.song_id
    JOIN artists a ON s.artist_id = a.id
    GROUP BY s.id, a.id, a.artist_name
    ORDER BY avg_score DESC, rating_count DESC
    LIMIT p_limit;
END //

-- 5. Top N 아티스트 (평가 많은 순)
DROP PROCEDURE IF EXISTS GetMostRatedArtists//
CREATE PROCEDURE GetMostRatedArtists(
    IN p_limit INT
)
BEGIN
    SELECT 
        a.id,
        a.artist_name,
        COUNT(r.id) as rating_count
    FROM artists a
    JOIN songs s ON a.id = s.artist_id
    JOIN rates r ON s.id = r.song_id
    GROUP BY a.id
    ORDER BY rating_count DESC
    LIMIT p_limit;
END //

-- 6. 아티스트 검색
DROP PROCEDURE IF EXISTS SearchArtists//
CREATE PROCEDURE SearchArtists(
    IN p_like_query VARCHAR(257),
    IN p_limit INT
)
BEGIN
    SELECT id, artist_name as text
    FROM artists
    WHERE artist_name LIKE p_like_query
    LIMIT p_limit;
END //

-- 7. 앨범 검색
DROP PROCEDURE IF EXISTS SearchAlbums//
CREATE PROCEDURE SearchAlbums(
    IN p_like_query VARCHAR(257),
    IN p_limit INT
)
BEGIN
    SELECT id, album_name as text
    FROM albums
    WHERE album_name LIKE p_like_query
    LIMIT p_limit;
END //

-- 8. 해시태그 검색
DROP PROCEDURE IF EXISTS SearchHashtags//
CREATE PROCEDURE SearchHashtags(
    IN p_like_query VARCHAR(100),
    IN p_limit INT
)
BEGIN
    SELECT id, content as text
    FROM hashtags
    WHERE content LIKE p_like_query
    LIMIT p_limit;
END //

-- 9. 해시태그로 노래 목록 가져오기
DROP PROCEDURE IF EXISTS GetSongsByHashtag//
CREATE PROCEDURE GetSongsByHashtag(
    IN p_hashtag_content VARCHAR(100)
)
BEGIN
    SELECT 
        s.id,
        s.song_name,
        ar.artist_name,
        ar.id as artist_id,
        al.album_name,
        al.id as album_id,
        s.release_date
    FROM songs s
    JOIN artists ar ON s.artist_id = ar.id
    LEFT JOIN albums al ON s.album_id = al.id
    JOIN notes n ON s.id = n.entity_id AND n.entity_type = 'song'
    JOIN hashtag_notes hn ON n.id = hn.note_id
    JOIN hashtags h ON hn.hashtag_id = h.id
    WHERE TRIM(LEADING '#' FROM h.content) = p_hashtag_content
    ORDER BY s.song_name;
END //

DELIMITER ;
