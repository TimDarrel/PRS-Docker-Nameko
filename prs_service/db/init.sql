-- ============================================================
-- PRS (Pembuatan Rencana Studi) Database Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS prs_db;
USE prs_db;

-- ----------------------------------------------------------
-- Table: PRS (header / rencana studi per mahasiswa)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS prs (
    id_prs          INT AUTO_INCREMENT PRIMARY KEY,
    id_mahasiswa    INT          NOT NULL,
    id_semester     INT          NOT NULL,
    dosen_wali_id   INT          NOT NULL,
    status          ENUM('draft', 'process', 'validated') NOT NULL DEFAULT 'draft',
    total_sks       INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_prs (id_mahasiswa, id_semester)
);

-- ----------------------------------------------------------
-- Table: PRS_Detail (kelas yang diambil dalam satu PRS)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS prs_detail (
    id_detail_prs   INT AUTO_INCREMENT PRIMARY KEY,
    id_prs          INT          NOT NULL,
    id_kelas        INT          NOT NULL,
    id_mata_kuliah  INT          NOT NULL,
    prioritas       TINYINT      NOT NULL DEFAULT 1,
    sks             INT          NOT NULL,
    status_validasi ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_detail (id_prs, id_kelas),
    FOREIGN KEY (id_prs) REFERENCES prs(id_prs) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Table: Jadwal_SS (snapshot of jadwal at enrollment time)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS jadwal_ss (
    id_jadwal_ss    INT AUTO_INCREMENT PRIMARY KEY,
    id_jadwal       INT          NOT NULL,               -- original ID from Penawaran Kelas
    id_detail_prs   INT          NOT NULL,
    jam_mulai       TIME         NOT NULL,
    jam_selesai     TIME         NOT NULL,
    hari            VARCHAR(20)  NOT NULL,
    ruangan         VARCHAR(50)  NOT NULL,
    tipe            ENUM('teori', 'praktikum') NOT NULL,
    is_outdated     TINYINT(1)   NOT NULL DEFAULT 0,
    snapshotted_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_detail_prs) REFERENCES prs_detail(id_detail_prs) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Seed: PRS data
-- ----------------------------------------------------------
INSERT INTO prs (id_mahasiswa, id_semester, dosen_wali_id, status, total_sks) VALUES
(1, 1, 10, 'draft',     0),
(2, 1, 10, 'process',   9),
(3, 1, 11, 'validated', 18);

-- ----------------------------------------------------------
-- Seed: PRS_Detail data
-- ----------------------------------------------------------
INSERT INTO prs_detail (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi) VALUES
(2, 101, 1, 1, 3, 'pending'),
(2, 102, 2, 2, 3, 'pending'),
(2, 103, 3, 3, 3, 'pending'),
(3, 104, 4, 1, 3, 'approved'),
(3, 105, 5, 2, 3, 'approved'),
(3, 106, 6, 1, 3, 'approved'),
(3, 107, 7, 2, 3, 'approved'),
(3, 108, 8, 3, 3, 'approved'),
(3, 109, 1, 1, 3, 'rejected');

-- ----------------------------------------------------------
-- Seed: Jadwal_SS data (snapshot per prs_detail row)
-- id_detail_prs 1 = kelas 101, id_detail_prs 2 = kelas 102, etc.
-- ----------------------------------------------------------
INSERT INTO jadwal_ss (id_jadwal, id_detail_prs, jam_mulai, jam_selesai, hari, ruangan, tipe, is_outdated) VALUES
-- prs_detail 1 (kelas 101) — teori only
(1001, 1, '08:00:00', '09:40:00', 'Senin',  'GKB1-101', 'teori', 0),

-- prs_detail 2 (kelas 102) — teori + praktikum
(1002, 2, '10:00:00', '11:40:00', 'Selasa', 'GKB1-202', 'teori', 0),
(1003, 2, '13:00:00', '14:40:00', 'Selasa', 'LAB-01',   'praktikum', 0),

-- prs_detail 3 (kelas 103) — teori only, outdated (jadwal changed in Penawaran Kelas)
(1004, 3, '08:00:00', '09:40:00', 'Rabu',   'GKB2-301', 'teori', 0),  

-- prs_detail 4 (kelas 104)
(1005, 4, '13:00:00', '14:40:00', 'Kamis',  'GKB1-103', 'teori', 0),

-- prs_detail 5 (kelas 105)
(1006, 5, '15:00:00', '16:40:00', 'Jumat',  'GKB2-201', 'teori', 0),
(1007, 5, '07:00:00', '08:40:00', 'Sabtu',  'LAB-02',   'praktikum', 0),

-- prs_detail 6 (kelas 106)
(1008, 6, '10:00:00', '11:40:00', 'Senin',  'GKB1-205', 'teori', 0),

-- prs_detail 7 (kelas 107)
(1009, 7, '13:00:00', '14:40:00', 'Selasa', 'GKB2-101', 'teori', 0),
(1010, 7, '15:00:00', '16:40:00', 'Rabu',   'LAB-03',   'praktikum', 0),

-- prs_detail 8 (kelas 108)
(1011, 8, '08:00:00', '09:40:00', 'Kamis',  'GKB1-301', 'teori', 0),

-- prs_detail 9 (kelas 109, rejected)
(1012, 9, '10:00:00', '11:40:00', 'Jumat',  'GKB2-102', 'teori', 0);